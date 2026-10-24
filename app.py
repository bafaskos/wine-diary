# Ιστορικό εκδόσεων (αυξάνουμε τον αριθμό σε κάθε βελτίωση)
# ver. 2.6  πολλές φωτογραφίες (έως 6): κάμερα ή αρχείο, διαγραφή, αυτόματη αποθήκευση
# ver. 2.5  σημειώσεις πριν το άνοιγμα, αυτόματη αποθήκευση κάθε 10", εκκαθάριση φόρμας, ανάκτηση πρόχειρων
# ver. 2.4  υποσέλιδο © και ένδειξη έκδοσης
# ver. 2.3  σταθερές θέσεις μηνυμάτων: οι καρτέλες δεν «πηδούν» πια
# ver. 2.2  διόρθωση: προσθήκη στήλης status, χωρίς διπλά κρασιά
# ver. 2.0  προσωρινή / οριστική αποθήκευση, τυφλή γευσιγνωσία, αποκάλυψη, φωτογραφίες, όροι αφρωδών
# ver. 1.0  βασική εφαρμογή: νέα, επανάληψη, ευρετήριο, αρώματα
import base64
import io
import unicodedata
from datetime import date, datetime

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

try:
    from st_keyup import st_keyup  # αναζήτηση σε κάθε πάτημα πλήκτρου
except ImportError:
    st_keyup = None

SHEET_ID = "1WKbDTO6JPEu-1bavrJuqNnvqT5I-2HkLnfm_cWNc44Y"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
VERSION = "2.6"
st.set_page_config(page_title="Ημερολόγιο Κρασιού", page_icon="🍷", layout="centered")


# ---------------------------------------------------------------- Google Sheets
@st.cache_resource
def get_book():
    try:  # στο cloud: Secrets. Τοπικά: credentials.json
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    except Exception:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    try:
        sid = st.secrets["sheet_id"]
    except Exception:
        sid = SHEET_ID
    return gspread.authorize(creds).open_by_key(sid)


@st.cache_data(ttl=600)
def load_static():
    book = get_book()
    return (pd.DataFrame(book.worksheet("Options").get_all_records()),
            pd.DataFrame(book.worksheet("Aromas").get_all_records()))


@st.cache_data(ttl=30)
def load(sheet):
    return pd.DataFrame(get_book().worksheet(sheet).get_all_records())


def next_id(ws, prefix):
    nums = [int(x[1:]) for x in ws.col_values(1)[1:] if x[1:].isdigit()]
    return f"{prefix}{max(nums, default=0) + 1:04d}"


def upsert(ws, key, row):  # ενημερώνει τη γραμμή αν υπάρχει, αλλιώς προσθέτει (με βάση το όνομα στήλης)
    heads = ws.row_values(1)
    if ws.title == "TastingSessions":
        for c in ("status", "pre_notes"):
            if c not in heads:
                if len(heads) + 1 > ws.col_count:
                    ws.add_cols(1)  # το φύλλο δεν έχει χώρο για νέα στήλη
                ws.update_cell(1, len(heads) + 1, c)
                heads.append(c)
    vals = [row.get(h, "") for h in heads]
    ids = ws.col_values(1)
    if key in ids:
        ws.update(values=[vals], range_name=f"A{ids.index(key) + 1}", value_input_option="RAW")
    else:
        ws.append_row(vals, value_input_option="RAW")


def shrink(f):  # μικρογραφία JPEG (έως 900px) από αρχείο ή κάμερα
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
    im.thumbnail((900, 900))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=60)
    return buf.getvalue()


def store_photo(book, key, data):  # φωτογραφία σε κομμάτια στο φύλλο Photos (κλειδί: S0001#3)
    b = base64.b64encode(data).decode()
    try:
        ws = book.worksheet("Photos")
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet("Photos", 1000, 3)
        ws.append_row(["session_id", "part", "data"])
    ws.append_rows([[key, i, b[j:j + 45000]] for i, j in enumerate(range(0, len(b), 45000))],
                   value_input_option="RAW")


def get_photos(sid):  # [(κλειδί, bytes)] όλων των φωτογραφιών μιας δοκιμής
    try:
        ph = load("Photos")
        ph = ph[ph["session_id"].astype(str).map(lambda k: k == sid or k.startswith(sid + "#"))]
        return [(k, base64.b64decode("".join(g.sort_values("part")["data"].astype(str))))
                for k, g in ph.groupby("session_id", sort=False)]
    except Exception:
        return []


def del_photo_rows(book, key, prefix=False):  # σβήνει τις γραμμές μιας φωτογραφίας (ή όλων της δοκιμής)
    try:
        ws = book.worksheet("Photos")
    except gspread.WorksheetNotFound:
        return
    idx = [i + 1 for i, k in enumerate(ws.col_values(1)) if k == key or (prefix and k.startswith(key + "#"))]
    blocks = []
    for i in idx:
        if blocks and blocks[-1][1] == i - 1:
            blocks[-1][1] = i
        else:
            blocks.append([i, i])
    for x, y in reversed(blocks):
        ws.delete_rows(x, y)


def show_photo(sid):
    for _, b in get_photos(sid):
        st.image(b)


SPARK_SUGAR = ["Brut Nature (0-3 g/L)", "Extra Brut (0-6 g/L)", "Brut (έως 12 g/L)",
               "Extra Dry (12-17 g/L)", "Sec / Dry (17-32 g/L)", "Demi-Sec (32-50 g/L)",
               "Doux (πάνω από 50 g/L)"]


OPT, AROMAS = load_static()
AROMA_NAMES = AROMAS["aroma"].astype(str).tolist()


def opts(field, *applies):
    d = OPT[OPT["field"] == field]
    if applies:
        d = d[d["applies_to"].apply(
            lambda a: a == "όλα" or any(x in str(a).split(";") for x in applies))]
    return d["value"].astype(str).tolist()


def norm(s):  # χωρίς τόνους / κεφαλαία / τελικό ς
    s = unicodedata.normalize("NFD", str(s).lower().replace("ς", "σ"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def one(label, options, key):
    if st.session_state.get(key) not in (None, *options):  # η επιλογή δεν ισχύει πια (π.χ. άλλαξε κατηγορία)
        st.session_state[key] = None
    return st.pills(label, options, key=key) or ""


def many(label, options, key):
    return "; ".join(st.pills(label, options, selection_mode="multi", key=key) or [])


def num(v):
    return "" if v is None else v


# ---------------------------------------------------------------- επιλογέας αρωμάτων
def group_pills(k, wkey, label, options):
    sel_key = f"{k}_sel"

    def sync():
        keep = [a for a in st.session_state[sel_key] if a not in options]
        st.session_state[sel_key] = keep + list(st.session_state[wkey] or [])

    st.session_state[wkey] = [a for a in options if a in st.session_state[sel_key]]
    st.pills(label, options, selection_mode="multi", key=wkey, on_change=sync)


def picker(k, title):
    sel_key = f"{k}_sel"
    sel = st.session_state.setdefault(sel_key, [])

    def drop():
        st.session_state[sel_key] = list(st.session_state[k + "_ms"])

    st.markdown(f"**{title}**")
    st.session_state[k + "_ms"] = list(sel)
    st.multiselect("Επιλεγμένα", sel, key=k + "_ms", on_change=drop,
                   label_visibility="collapsed", placeholder="Κανένα ακόμα")
    box = st_keyup if st_keyup else st.text_input
    q = norm(box("🔍 Αναζήτηση (από ένα γράμμα και πάνω)", key=k + "_q") or "")
    if q:
        rows = []
        for a in AROMA_NAMES:
            n = norm(a)
            if n.startswith(q):
                rows.append((0, a))
            elif any(w.startswith(q) for w in n.split()):
                rows.append((1, a))
            elif q in n:
                rows.append((2, a))
        found = [a for _, a in sorted(rows)][:40]
        if found:
            group_pills(k, f"{k}_s{abs(hash(tuple(found)))}", "Αποτελέσματα", found)
        else:
            st.caption("Δεν βρέθηκε άρωμα.")
        return
    A = AROMAS.assign(cat=AROMAS["category_icon"] + " " + AROMAS["category"],
                      grp=AROMAS["group_icon"] + " " + AROMAS["group"])
    cat = st.pills("Κατηγορία", list(dict.fromkeys(A["cat"])), key=k + "_cat")
    if cat:
        sub = A[A["cat"] == cat]
        for gi, g in enumerate(dict.fromkeys(sub["grp"])):
            group_pills(k, f"{k}_g{gi}", g, sub[sub["grp"] == g]["aroma"].astype(str).tolist())


# ---------------------------------------------------------------- φόρμες
def bottle_ui(p):
    w = {}
    w["wine_name"] = st.text_input("Όνομα κρασιού *", key=f"{p}_wine_name")
    for f, lab in [("winery", "Οινοποιείο"), ("vintage", "Χρονιά"),
                   ("grape_variety", "Ποικιλία"), ("region", "Περιοχή"),
                   ("country", "Χώρα"), ("purchase_source", "Σημείο αγοράς")]:
        w[f] = st.text_input(lab, key=f"{p}_{f}")
    c1, c2 = st.columns(2)
    w["alcohol_degree"] = num(c1.number_input("Αλκοόλ %", 0.0, 25.0, value=None, step=0.1,
                                              key=f"{p}_alcohol_degree"))
    w["purchase_price"] = num(c2.number_input("Τιμή €", 0.0, value=None, step=0.5,
                                              key=f"{p}_purchase_price"))
    w["wine_category"] = one("Κατηγορία", opts("wine_category"), f"{p}_wine_category")
    w["wine_category_other"] = ""
    if w["wine_category"] == "Άλλο":
        w["wine_category_other"] = st.text_input("Τι εννοείς με «Άλλο»;", key=f"{p}_cat_other")
    w["is_sparkling"] = "Ναι" if st.toggle("Αφρώδες", key=f"{p}_is_sparkling") else "Όχι"
    return w


MAXPH = 6


def add_photos(p, src):  # κουμπί «Προσθήκη»: μικραίνει και κρατά τις φωτογραφίες στη φόρμα
    S = st.session_state
    n = S.get(f"{p}_pn", 0)
    got = S.get(f"{p}_p{src}_{n}")
    lst = S.setdefault(f"{p}_photos", [])
    for f in (got if isinstance(got, list) else [got] if got else []):
        if len(lst) >= MAXPH:
            S["_flash"] = f"Έως {MAXPH} φωτογραφίες ανά δοκιμή."
            break
        c = S.get(f"{p}_pidc", 0)
        S[f"{p}_pidc"] = c + 1
        lst.append({"id": c, "bytes": shrink(f), "saved": False, "key": None})
    S[f"{p}_pn"] = n + 1  # νέα, κενά πεδία επιλογής


def remove_photo(p, pid):
    S = st.session_state
    lst = S.get(f"{p}_photos", [])
    ph = next((x for x in lst if x["id"] == pid), None)
    if ph is None:
        return
    if ph["saved"] and ph.get("key"):
        try:
            del_photo_rows(get_book(), ph["key"])
            load.clear()
        except Exception as e:
            S["_flash"] = f"Σφάλμα διαγραφής φωτογραφίας: {e}"
            return
    S[f"{p}_photos"] = [x for x in lst if x["id"] != pid]


def photos_ui(p):
    S = st.session_state
    lst = S.setdefault(f"{p}_photos", [])
    n = S.get(f"{p}_pn", 0)
    st.markdown(f"**📷 Φωτογραφίες ({len(lst)}/{MAXPH})**")
    if lst:
        cols = st.columns(3)
        for i, ph in enumerate(lst):
            with cols[i % 3]:
                st.image(ph["bytes"], width=100)
                st.button("✕", key=f"{p}_rm_{ph['id']}", on_click=remove_photo, args=(p, ph["id"]))
    if len(lst) < MAXPH:
        st.file_uploader("🖼️ Από αρχείο (μπορείς πολλές μαζί)", type=["jpg", "jpeg", "png"],
                         accept_multiple_files=True, key=f"{p}_pfile_{n}")
        st.button("➕ Προσθήκη από αρχείο", key=f"{p}_addf", on_click=add_photos, args=(p, "file"))
        if st.toggle("Άνοιγμα κάμερας", key=f"{p}_camon"):
            st.camera_input("📷 Κάμερα", key=f"{p}_pcam_{n}")
            st.button("➕ Προσθήκη φωτογραφίας", key=f"{p}_addc", on_click=add_photos, args=(p, "cam"))


STEPS = ["Στοιχεία", "Όψη", "Μύτη", "Στόμα", "Συμπέρασμα"]
BOTTLE_F = ["wine_name", "winery", "vintage", "grape_variety", "region", "country", "purchase_source",
            "alcohol_degree", "purchase_price", "wine_category"]
D_F = ["pre_notes", "tasting_date", "tasting_context", "serving_temp", "decanting", "visual_color", "visual_highlights",
       "tears", "bubbles_size", "bubbles_duration", "bubbles_beads", "appearance_comments", "flaws_presence",
       "flaws_list", "aroma_intensity", "aroma_duration", "aroma_quality", "nose_comments", "body_structure",
       "sugar_level", "alcohol_level", "acidity", "tannins", "palate_duration", "aftertaste",
       "aftertaste_seconds", "sparkling_texture", "palate_comments", "readiness_state", "food_pairing",
       "overall_rating", "notes"]


def val(p, f):  # τρέχουσα τιμή πεδίου από τη μνήμη της φόρμας (ακόμα κι αν το βήμα δεν φαίνεται)
    v = st.session_state.get(f"{p}_{f}")
    if v is None:
        return ""
    if isinstance(v, list):
        return "; ".join(v)
    return str(v) if isinstance(v, date) else v


def nav_bar(label, options, key):
    if not st.session_state.get(key):
        st.session_state[key] = options[0]
    return st.segmented_control(label, options, key=key, label_visibility="collapsed") or options[0]


def tasting_ui(p, wine=None, blind=False):
    S = st.session_state
    step = nav_bar("Βήμα", STEPS, f"{p}_step")
    if wine is not None:
        w = wine
    else:
        w = {f: val(p, f) for f in BOTTLE_F}
        w["wine_category_other"] = val(p, "cat_other") if w["wine_category"] == "Άλλο" else ""
        w["is_sparkling"] = "Ναι" if S.get(f"{p}_is_sparkling") else "Όχι"
    cat, spark = w.get("wine_category", ""), w.get("is_sparkling") == "Ναι"

    if step == "Στοιχεία":
        st.text_area("📝 Σημειώσεις πριν το άνοιγμα", key=f"{p}_pre_notes")
        if blind:
            one("Κατηγορία (όπως την κρίνεις)", opts("wine_category"), f"{p}_wine_category")
            st.toggle("Αφρώδες", key=f"{p}_is_sparkling")
            st.number_input("Αριθμός δείγματος *", 1, value=None, step=1, key=f"{p}_blind_sample_number")
        elif wine is None:
            bottle_ui(p)
        else:
            st.info(f"🔒 {w['wine_name']} · {w['winery']} · {w['vintage']} · {w['country']} · {w['wine_category']}")
        st.divider()
        kd = f"{p}_tasting_date"
        if kd in S:
            st.date_input("Ημερομηνία", key=kd)
        else:
            st.date_input("Ημερομηνία", date.today(), key=kd)
        st.text_input("Πλαίσιο δοκιμής", key=f"{p}_tasting_context")
        one("Θερμοκρασία σερβιρίσματος", opts("serving_temp"), f"{p}_serving_temp")
        one("Καραφάκι / αερισμός", opts("decanting"), f"{p}_decanting")
        photos_ui(p)

    elif step == "Όψη":
        if not cat:
            st.caption("Διάλεξε πρώτα κατηγορία στα «Στοιχεία».")
        else:
            one("Απόχρωση", opts("visual_color", cat), f"{p}_visual_color")
            if opts("visual_highlights", cat):
                one("Ανταύγειες", opts("visual_highlights", cat), f"{p}_visual_highlights")
        one("Δάκρυα (1 = κοντές καμάρες, 5 = μακριά)", opts("tears"), f"{p}_tears")
        if spark:
            one("Μέγεθος φυσαλίδας", opts("bubbles_size"), f"{p}_bubbles_size")
            one("Διάρκεια αφρισμού", opts("bubbles_duration"), f"{p}_bubbles_duration")
            one("Κορδόνια", opts("bubbles_beads"), f"{p}_bubbles_beads")
        st.text_area("Σημειώσεις όψης", key=f"{p}_appearance_comments")

    elif step == "Μύτη":
        one("Κατάσταση", opts("flaws_presence"), f"{p}_flaws_presence")
        if S.get(f"{p}_flaws_presence") == "Ελαττωματική":
            many("Ελαττώματα", opts("flaws_list"), f"{p}_flaws_list")
        one("Ένταση", opts("aroma_intensity"), f"{p}_aroma_intensity")
        one("Διάρκεια", opts("aroma_duration"), f"{p}_aroma_duration")
        one("Ποιότητα", opts("aroma_quality"), f"{p}_aroma_quality")
        picker(f"{p}_nose_aromas", "Αρώματα μύτης")
        st.text_area("Σημειώσεις μύτης", key=f"{p}_nose_comments")

    elif step == "Στόμα":
        one("Σώμα", opts("body_structure"), f"{p}_body_structure")
        one("Σάκχαρα (όροι δοσολογίας αφρωδών)" if spark else "Σάκχαρα",
            (opts("sugar_level_sparkling") or SPARK_SUGAR) if spark else opts("sugar_level"), f"{p}_sugar_level")
        one("Αλκοόλη", opts("alcohol_level"), f"{p}_alcohol_level")
        one("Οξύτητα", opts("acidity"), f"{p}_acidity")
        if opts("tannins", cat):
            one("Τανίνες", opts("tannins", cat), f"{p}_tannins")
        one("Διάρκεια", opts("palate_duration"), f"{p}_palate_duration")
        one("Επίγευση", opts("aftertaste"), f"{p}_aftertaste")
        st.number_input("Επίγευση σε δευτερόλεπτα (προαιρετικό)", 0, value=None, step=1,
                        key=f"{p}_aftertaste_seconds")
        st.caption(" · ".join(opts("aftertaste_seconds_guide")))
        if spark:
            one("Αφρώδες στο στόμα", opts("sparkling_texture"), f"{p}_sparkling_texture")
        st.button("⬇️ Αντιγραφή αρωμάτων από Μύτη", key=f"{p}_cp_nose",
                  on_click=lambda: S.update({f"{p}_palate_aromas_sel": list(S.get(f"{p}_nose_aromas_sel", []))}))
        picker(f"{p}_palate_aromas", "Αρώματα / γεύσεις στόματος")
        st.text_area("Σημειώσεις στόματος", key=f"{p}_palate_comments")

    else:
        one("Φάση ετοιμότητας", opts("readiness_state"), f"{p}_readiness_state")
        st.text_input("Συνδυασμός με φαγητό", key=f"{p}_food_pairing")
        st.number_input("Συνολική βαθμολογία (0-5)", 0.0, 5.0, value=None, step=0.5, key=f"{p}_overall_rating")
        if blind:
            st.text_input("Εκτίμηση: ποικιλία", key=f"{p}_guess_grape")
            st.text_input("Εκτίμηση: περιοχή / χώρα", key=f"{p}_guess_region_country")
            st.text_input("Εκτίμηση: χρονιά", key=f"{p}_guess_vintage")
        st.text_area("Τελική γνώμη του δοκιμαστή", key=f"{p}_notes")

    d = {f: val(p, f) for f in D_F}
    d["nose_aromas"] = "; ".join(S.get(f"{p}_nose_aromas_sel", []))
    d["palate_aromas"] = "; ".join(S.get(f"{p}_palate_aromas_sel", []))
    sugar = (opts("sugar_level_sparkling") or SPARK_SUGAR) if spark else opts("sugar_level")
    for f, o in (("visual_color", opts("visual_color", cat)), ("visual_highlights", opts("visual_highlights", cat)),
                 ("tannins", opts("tannins", cat)), ("sugar_level", sugar)):
        if d[f] not in o:  # ξεχασμένη επιλογή που δεν ισχύει πια
            d[f] = ""
    if not spark:
        for f in ("bubbles_size", "bubbles_duration", "bubbles_beads", "sparkling_texture"):
            d[f] = ""
    if d["flaws_presence"] != "Ελαττωματική":
        d["flaws_list"] = ""
    if blind:
        d.update(blind_sample_number=val(p, "blind_sample_number"), blind_category=cat,
                 blind_sparkling=w["is_sparkling"])
        d.update({f: val(p, f) for f in ("guess_grape", "guess_region_country", "guess_vintage")})
    d["_photos"] = S.setdefault(f"{p}_photos", [])
    return w, d


def save(p, kind, w, d, wid=None, blind=False, final=False, auto=False):
    S = st.session_state
    if not blind and wid is None and not str(w.get("wine_name", "")).strip():
        if not auto:
            st.error("Γράψε το όνομα του κρασιού.")
        return False
    if blind and not d.get("blind_sample_number"):
        if not auto:
            st.error("Βάλε αριθμό δείγματος.")
        return False
    ids = dict(S.get(f"{p}_ids", {}))
    try:
        book, now = get_book(), datetime.now().strftime("%Y-%m-%d %H:%M")
        if not blind and wid is None:
            wid = ids.get("wid") or next_id(book.worksheet("Wines"), "W")
            ids["wid"] = wid
            v = str(w["vintage"]).strip()
            ids["wc"] = ids.get("wc") or now
            upsert(book.worksheet("Wines"), wid,
                   {**w, "vintage": int(v) if v.isdigit() else v, "wine_id": wid, "created_at": ids["wc"]})
        ws = book.worksheet("TastingSessions")
        sid = ids.get("sid") or next_id(ws, "S")
        ids["sc"] = ids.get("sc") or now
        row = {**d, "session_id": sid, "wine_id": wid or "", "is_blind": "Ναι" if blind else "Όχι",
               "status": "Οριστικό" if final else "Πρόχειρο", "created_at": ids["sc"]}
        photos = d.get("_photos") or []
        for ph in photos:
            if not ph["saved"]:
                ph["key"] = ph.get("key") or f"{sid}#{ph['id']}"
                store_photo(book, ph["key"], ph["bytes"])
                ph["saved"] = True
        row["photo"] = f"Photos:{sid}" if photos else ""
        upsert(ws, sid, row)
    except Exception as e:
        S[f"{p}_ids"] = ids  # ώστε η επόμενη προσπάθεια να μη δημιουργήσει νέο κρασί
        if auto:
            st.caption(f"⚠️ Η αυτόματη αποθήκευση απέτυχε: {e}")
        else:
            st.error(f"Σφάλμα αποθήκευσης: {e}")
        return False
    ids.update(wid=wid, sid=sid)
    S[f"{p}_ids"] = ids
    load.clear()
    if final:
        S["v_" + kind] += 1  # νέα κενή φόρμα
        S["_flash"] = f"Οριστική καταχώρηση: {sid}"
        st.rerun()
    return True


FLOATF, INTF = {"overall_rating", "alcohol_degree", "purchase_price"}, {"aftertaste_seconds", "blind_sample_number"}
SKIP = {"pre_notes", "session_id", "wine_id", "tasting_date", "created_at", "is_blind", "photo", "status",
        "blind_sample_number", "blind_category", "blind_sparkling"}
SKIP_DRAFT = {"session_id", "wine_id", "created_at", "is_blind", "photo", "status",
              "blind_category", "blind_sparkling"}


def fill(p, rec, skip):  # γεμίζει τα πεδία της φόρμας από μια εγγραφή
    S = st.session_state
    for f, v in rec.items():
        if f in skip or str(v).strip() == "":
            continue
        k, lst = f"{p}_{f}", [x.strip() for x in str(v).split(";") if x.strip()]
        if f in ("nose_aromas", "palate_aromas"):
            S[k + "_sel"] = lst
        elif f == "flaws_list":
            S[k] = lst
        elif f in FLOATF:
            S[k] = float(v)
        elif f in INTF:
            S[k] = int(float(v))
        elif f == "tasting_date":
            S[k] = date.fromisoformat(str(v)[:10])
        elif f == "is_sparkling":
            S[k] = v == "Ναι"
        elif f == "wine_category_other":
            S[f"{p}_cat_other"] = str(v)
        else:
            S[k] = str(v)


def copy_prev(p, wid):
    s = load("TastingSessions")
    s = s[s["wine_id"] == wid]
    if not s.empty:
        fill(p, s.sort_values("tasting_date").iloc[-1].to_dict(), SKIP)


def load_draft(p, sid):
    S = st.session_state
    s = load("TastingSessions")
    r = s[s["session_id"] == sid].iloc[0].to_dict()
    blind = r.get("is_blind") == "Ναι"
    S[f"{p}_blind"] = blind
    ids = {"sid": sid, "sc": r.get("created_at"), "photo": bool(str(r.get("photo", "")).strip())}
    if blind:
        r["wine_category"], r["is_sparkling"] = r.get("blind_category", ""), r.get("blind_sparkling", "")
    elif str(r.get("wine_id", "")).strip():
        wn = load("Wines")
        wr = wn[wn["wine_id"] == r["wine_id"]].iloc[0].to_dict()
        ids.update(wid=wr["wine_id"], wc=wr.get("created_at"))
        r.update({k: v for k, v in wr.items() if k != "created_at"})
    fill(p, r, SKIP_DRAFT)
    lst = []
    for k, b in get_photos(sid):
        pid = int(k.split("#")[1]) if "#" in k and k.split("#")[1].isdigit() else 0
        lst.append({"id": pid, "bytes": b, "saved": True, "key": k})
    S[f"{p}_photos"] = lst
    S[f"{p}_pidc"] = max([x["id"] for x in lst], default=-1) + 1
    S[f"{p}_ids"] = ids


def index_tab():
    ses, wines = load("TastingSessions"), load("Wines")
    if ses.empty or wines.empty:
        st.info("Δεν υπάρχουν ακόμα δοκιμές.")
        return
    df = ses.merge(wines[["wine_id", "wine_name", "winery", "vintage", "wine_category"]],
                   on="wine_id", how="left")
    q = norm(st.text_input("🔍 Αναζήτηση (όνομα, οινοποιείο, πλαίσιο)", key="ix_q"))
    if q:
        txt = df[["wine_name", "winery", "tasting_context"]].astype(str).agg(" ".join, axis=1).map(norm)
        df = df[txt.str.contains(q, regex=False)]
    df = df.sort_values("tasting_date", ascending=False)
    st.dataframe(df[["tasting_date", "wine_name", "winery", "vintage", "overall_rating"]], hide_index=True)
    pick = st.selectbox("Άνοιγμα δοκιμής", df["session_id"], index=None,
                        format_func=lambda s: f"{s} · {df[df['session_id'] == s].iloc[0]['wine_name']}")
    if pick:
        show_photo(pick)
        for k, v in df[df["session_id"] == pick].iloc[0].items():
            if str(v).strip():
                st.markdown(f"**{k}:** {v}")


def discard(sid):  # διαγράφει ΜΟΝΟ πρόχειρο (και το κρασί του, αν δεν το χρησιμοποιεί άλλη δοκιμή)
    book = get_book()
    ws = book.worksheet("TastingSessions")
    heads, ids = ws.row_values(1), ws.col_values(1)
    if sid not in ids or "status" not in heads:
        return
    r = ids.index(sid) + 1
    if ws.cell(r, heads.index("status") + 1).value != "Πρόχειρο":
        return
    ci = heads.index("wine_id") + 1
    wid = ws.cell(r, ci).value
    del_photo_rows(book, sid, prefix=True)
    ws.delete_rows(r)
    if wid and wid not in ws.col_values(ci)[1:]:
        wn = book.worksheet("Wines")
        wids = wn.col_values(1)
        if wid in wids:
            wn.delete_rows(wids.index(wid) + 1)
    load.clear()


def discard_cb(sid):
    try:
        discard(sid)
        st.session_state["_flash"] = f"Διαγράφηκε το πρόχειρο {sid}."
    except Exception as e:
        st.session_state["_flash"] = f"Σφάλμα διαγραφής: {e}"


def clear_form(p, kind):
    S = st.session_state
    sid = S.get(f"{p}_ids", {}).get("sid")
    try:
        if sid:
            discard(sid)
        S["_flash"] = "Η φόρμα καθαρίστηκε."
    except Exception as e:
        S["_flash"] = f"Σφάλμα εκκαθάρισης: {e}"
    S["v_" + kind] += 1


def clear_ui(p, kind):  # επιβεβαίωση εκκαθάρισης
    S = st.session_state
    if S.get(f"{p}_confirm"):
        st.warning("Θα καθαριστεί η φόρμα και θα διαγραφεί το πρόχειρό της. Σίγουρα;")
        a, b = st.columns(2)
        a.button("Ναι, διαγραφή", key=f"{p}_yes", on_click=clear_form, args=(p, kind))
        b.button("Όχι", key=f"{p}_no", on_click=lambda: S.update({f"{p}_confirm": False}))


def drafts_ui(p):  # πρόχειρα που βρέθηκαν (π.χ. μετά από Πίσω / ανανέωση)
    if st.session_state.get(f"{p}_ids"):
        return
    ses, wines = load("TastingSessions"), load("Wines")
    if "status" not in ses.columns:
        return
    dr = ses[ses["status"] == "Πρόχειρο"].sort_values("created_at", ascending=False).head(5)
    names = dict(zip(wines["wine_id"], wines["wine_name"])) if not wines.empty else {}
    for r in dr.to_dict("records"):
        label = (f"🕶️ Τυφλή #{r.get('blind_sample_number')}" if r.get("is_blind") == "Ναι"
                 else names.get(r["wine_id"], r["wine_id"]))
        c1, c2, c3 = st.columns([5, 2, 2])
        c1.markdown(f"📝 **{label}** · {r['tasting_date']}")
        c2.button("Συνέχεια", key=f"{p}_c_{r['session_id']}", on_click=load_draft, args=(p, r["session_id"]))
        c3.button("Διαγραφή", key=f"{p}_d_{r['session_id']}", on_click=discard_cb, args=(r["session_id"],))


@st.fragment(run_every="10s")
def autosave(p, kind):  # αποθηκεύει το πρόχειρο κάθε 10", μόνο αν άλλαξε κάτι
    S = st.session_state
    snap = S.get(f"{p}_snap")
    if snap:
        w, d, blind, wid = snap
        key = repr((sorted((k, str(v)) for k, v in {**w, **d}.items() if not k.startswith("_")),
                    tuple(x["id"] for x in d.get("_photos", []))))
        has_d = bool(d.get("_photos")) or any(
            str(v).strip() for k, v in d.items()
            if not k.startswith("_") and k not in ("tasting_date", "blind_category", "blind_sparkling"))
        if blind:
            ok = bool(d.get("blind_sample_number"))
        else:
            ok = has_d if wid else bool(str(w.get("wine_name", "")).strip())
        if ok and key != S.get(f"{p}_hash") and save(p, kind, w, d, wid=wid, blind=blind, auto=True):
            S[f"{p}_hash"] = key
            S[f"{p}_last"] = datetime.now().strftime("%H:%M:%S")
    if S.get(f"{p}_last"):
        st.caption(f"💾 Αποθηκεύτηκε αυτόματα {S[f'{p}_last']}")


# ---------------------------------------------------------------- κύριο πρόγραμμα
S = st.session_state
for n in ("new", "rep", "rev"):
    S.setdefault("v_" + n, 0)  # αλλάζει μετά από οριστική καταχώρηση: νέα κενή φόρμα
pn, pr, pv = f"new{S['v_new']}", f"rep{S['v_rep']}", f"rv{S['v_rev']}"
NOKEEP = ("_sv", "_fin", "_copy", "_dopen", "_cp_nose", "_done", "_cam", "_file", "_q", "_clr", "_yes", "_no", "_addf", "_addc")
for k in list(S):  # κρατά τις τιμές της φόρμας όταν αλλάζεις ενότητα ή βήμα
    if k.startswith((pn + "_", pr + "_", pv + "_", "ix_")) and not k.endswith(NOKEEP) and not any(x in k for x in ("_c_S", "_d_S", "_rm_", "_pcam_", "_pfile_")):
        S[k] = S[k]
with st.container():  # σταθερή θέση για τα μηνύματα, ώστε να μη «πηδούν» οι καρτέλες
    if S.get("_flash"):
        st.success(S.pop("_flash"))

st.title("🍷 Ημερολόγιο Κρασιού")
NAVS = ["➕ Νέα", "🔁 Επανάληψη", "🎭 Αποκάλυψη", "📚 Ευρετήριο"]
nav = nav_bar("Ενότητα", NAVS, "nav")

if nav == NAVS[0]:
    with st.container():  # σταθερή θέση: ό,τι εμφανίζεται εδώ δεν μετακινεί ό,τι υπάρχει από κάτω
        drafts_ui(pn)
    blind = st.toggle("🕶️ Τυφλή γευσιγνωσία", key=f"{pn}_blind")
    w, d = tasting_ui(pn, blind=blind)
    S[f"{pn}_snap"] = (w, d, blind, None)
    c1, c2 = st.columns(2)
    c1.button("🗑️ Εκκαθάριση φόρμας", key=f"{pn}_clr", on_click=lambda: S.update({f"{pn}_confirm": True}))
    if c2.button("✅ Οριστική καταχώρηση", type="primary", key=f"{pn}_fin"):
        save(pn, "new", w, d, blind=blind, final=True)
    clear_ui(pn, "new")
    autosave(pn, "new")

elif nav == NAVS[1]:
    wines = load("Wines")
    if wines.empty:
        st.info("Δεν υπάρχουν ακόμα κρασιά.")
    else:
        rows = {f"{r['wine_id']} · {r['wine_name']} {r['vintage']} · {r['winery']}": r
                for r in wines.to_dict("records")}
        pick = st.selectbox("Κρασί", list(rows), index=None, key=f"{pr}_pick")
        if pick:
            wine = rows[pick]
            st.button("📋 Αντιγραφή από προηγούμενη δοκιμή", key=f"{pr}_copy",
                      on_click=copy_prev, args=(pr, wine["wine_id"]))
            w2, d2 = tasting_ui(pr, wine)
            S[f"{pr}_snap"] = (w2, d2, False, wine["wine_id"])
            c1, c2 = st.columns(2)
            c1.button("🗑️ Εκκαθάριση φόρμας", key=f"{pr}_clr", on_click=lambda: S.update({f"{pr}_confirm": True}))
            if c2.button("✅ Οριστική καταχώρηση", type="primary", key=f"{pr}_fin"):
                save(pr, "rep", w2, d2, wid=wine["wine_id"], final=True)
            clear_ui(pr, "rep")
            autosave(pr, "rep")

elif nav == NAVS[2]:
    ses, wines = load("TastingSessions"), load("Wines")
    pend = (ses[(ses["is_blind"] == "Ναι") & (ses["wine_id"].astype(str).str.strip() == "")]
            if "is_blind" in ses.columns else ses.iloc[0:0])
    if pend.empty:
        st.info("Δεν υπάρχουν τυφλές δοκιμές σε αναμονή αποκάλυψης.")
    else:
        sid = st.selectbox("Δείγμα", pend["session_id"], index=None, key=f"{pv}_pick",
                           format_func=lambda x: "Δείγμα {} · {}".format(
                               pend[pend["session_id"] == x].iloc[0]["blind_sample_number"],
                               pend[pend["session_id"] == x].iloc[0]["tasting_date"]))
        if sid:
            r = {k: (v.item() if hasattr(v, "item") else v)
                 for k, v in pend[pend["session_id"] == sid].iloc[0].items()}
            st.info(f"Η εκτίμησή σου: {r.get('guess_grape')} | {r.get('guess_region_country')} | "
                    f"{r.get('guess_vintage')}")
            new = st.radio("Το κρασί είναι", ["Νέο", "Υπάρχον"], horizontal=True, key=f"{pv}_mode") == "Νέο"
            if new:
                wr = bottle_ui(pv)
            else:
                lab = {f"{x['wine_id']} · {x['wine_name']}": x["wine_id"] for x in wines.to_dict("records")}
                wr = {"wine_id": lab.get(st.selectbox("Κρασί", list(lab), index=None, key=f"{pv}_ex"))}
            for f, lbl in [("guess_grape_result", "ποικιλίας"), ("guess_region_country_result", "περιοχής / χώρας"),
                           ("guess_vintage_result", "χρονιάς")]:
                r[f] = one(f"Αποτέλεσμα εκτίμησης {lbl}", opts("guess_result"), f"{pv}_{f}")
            if st.button("✅ Ολοκλήρωση αποκάλυψης", type="primary", key=f"{pv}_done"):
                if new and not str(wr.get("wine_name", "")).strip():
                    st.error("Γράψε το όνομα του κρασιού.")
                elif not new and not wr["wine_id"]:
                    st.error("Διάλεξε κρασί.")
                else:
                    try:
                        book, wid = get_book(), wr.get("wine_id")
                        if new:
                            wid = next_id(book.worksheet("Wines"), "W")
                            v = str(wr["vintage"]).strip()
                            upsert(book.worksheet("Wines"), wid,
                                   {**wr, "vintage": int(v) if v.isdigit() else v, "wine_id": wid,
                                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")})
                        r["wine_id"] = wid
                        upsert(book.worksheet("TastingSessions"), sid, r)
                    except Exception as e:
                        st.error(f"Σφάλμα αποθήκευσης: {e}")
                    else:
                        load.clear()
                        S["v_rev"] += 1
                        S["_flash"] = f"Αποκαλύφθηκε το δείγμα ({sid}) → κρασί {wid}"
                        st.rerun()

else:
    index_tab()

st.divider()
st.caption(f"ver. {VERSION} · © Konstantinos Bafas")
