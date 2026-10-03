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
    if ws.title == "TastingSessions" and "status" not in heads:
        if len(heads) + 1 > ws.col_count:
            ws.add_cols(1)  # το φύλλο δεν έχει χώρο για νέα στήλη
        ws.update_cell(1, len(heads) + 1, "status")
        heads.append("status")
    vals = [row.get(h, "") for h in heads]
    ids = ws.col_values(1)
    if key in ids:
        ws.update(values=[vals], range_name=f"A{ids.index(key) + 1}", value_input_option="RAW")
    else:
        ws.append_row(vals, value_input_option="RAW")


def store_photo(book, sid, f):  # φωτογραφία σε μικρογραφία, σε κομμάτια στο φύλλο Photos
    from PIL import Image
    im = Image.open(f).convert("RGB")
    im.thumbnail((900, 900))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=60)
    b = base64.b64encode(buf.getvalue()).decode()
    try:
        ws = book.worksheet("Photos")
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet("Photos", 1000, 3)
        ws.append_row(["session_id", "part", "data"])
    ws.append_rows([[sid, i, b[j:j + 45000]] for i, j in enumerate(range(0, len(b), 45000))],
                   value_input_option="RAW")


def show_photo(sid):
    try:
        ph = load("Photos")
        parts = ph[ph["session_id"] == sid].sort_values("part")
        if len(parts):
            st.image(base64.b64decode("".join(parts["data"].astype(str))))
    except Exception:
        pass


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


def tasting_ui(p, wine=None, blind=False):
    t = st.tabs(["Στοιχεία", "Όψη", "Μύτη", "Στόμα", "Συμπέρασμα"])
    d = {}
    with t[0]:
        if blind:
            w = {"wine_category": one("Κατηγορία (όπως την κρίνεις)", opts("wine_category"), f"{p}_wine_category"),
                 "is_sparkling": "Ναι" if st.toggle("Αφρώδες", key=f"{p}_is_sparkling") else "Όχι"}
            d["blind_sample_number"] = num(st.number_input("Αριθμός δείγματος *", 1, value=None, step=1,
                                                           key=f"{p}_blind_sample_number"))
            d["blind_category"], d["blind_sparkling"] = w["wine_category"], w["is_sparkling"]
            st.divider()
        elif wine is None:
            w = bottle_ui(p)
            st.divider()
        else:
            w = wine
            st.info(f"🔒 {w['wine_name']} · {w['winery']} · {w['vintage']} · "
                    f"{w['country']} · {w['wine_category']}")
        d["tasting_date"] = str(st.date_input("Ημερομηνία", date.today(), key=f"{p}_tasting_date"))
        d["tasting_context"] = st.text_input("Πλαίσιο δοκιμής", key=f"{p}_tasting_context")
        d["serving_temp"] = one("Θερμοκρασία σερβιρίσματος", opts("serving_temp"), f"{p}_serving_temp")
        d["decanting"] = one("Καραφάκι / αερισμός", opts("decanting"), f"{p}_decanting")
        cam = st.camera_input("📷 Φωτογραφία", key=f"{p}_cam") if st.toggle("Άνοιγμα κάμερας", key=f"{p}_camon") else None
        up = st.file_uploader("🖼️ Φωτογραφία από αρχείο", type=["jpg", "jpeg", "png"], key=f"{p}_file")
        d["_photo"] = cam or up
    cat, spark = w.get("wine_category", ""), w.get("is_sparkling") == "Ναι"

    with t[1]:
        if not cat:
            st.caption("Διάλεξε πρώτα κατηγορία στα «Στοιχεία».")
        d["visual_color"] = one("Απόχρωση", opts("visual_color", cat), f"{p}_visual_color") if cat else ""
        hl = opts("visual_highlights", cat) if cat else []
        d["visual_highlights"] = one("Ανταύγειες", hl, f"{p}_visual_highlights") if hl else ""
        d["tears"] = one("Δάκρυα (1 = κοντές καμάρες, 5 = μακριά)", opts("tears"), f"{p}_tears")
        if spark:
            d["bubbles_size"] = one("Μέγεθος φυσαλίδας", opts("bubbles_size"), f"{p}_bubbles_size")
            d["bubbles_duration"] = one("Διάρκεια αφρισμού", opts("bubbles_duration"), f"{p}_bubbles_duration")
            d["bubbles_beads"] = one("Κορδόνια", opts("bubbles_beads"), f"{p}_bubbles_beads")
        d["appearance_comments"] = st.text_area("Σημειώσεις όψης", key=f"{p}_appearance_comments")

    with t[2]:
        d["flaws_presence"] = one("Κατάσταση", opts("flaws_presence"), f"{p}_flaws_presence")
        if d["flaws_presence"] == "Ελαττωματική":
            d["flaws_list"] = many("Ελαττώματα", opts("flaws_list"), f"{p}_flaws_list")
        d["aroma_intensity"] = one("Ένταση", opts("aroma_intensity"), f"{p}_aroma_intensity")
        d["aroma_duration"] = one("Διάρκεια", opts("aroma_duration"), f"{p}_aroma_duration")
        d["aroma_quality"] = one("Ποιότητα", opts("aroma_quality"), f"{p}_aroma_quality")
        picker(f"{p}_nose_aromas", "Αρώματα μύτης")
        d["nose_aromas"] = "; ".join(st.session_state.get(f"{p}_nose_aromas_sel", []))
        d["nose_comments"] = st.text_area("Σημειώσεις μύτης", key=f"{p}_nose_comments")

    with t[3]:
        d["body_structure"] = one("Σώμα", opts("body_structure"), f"{p}_body_structure")
        d["sugar_level"] = one("Σάκχαρα (όροι δοσολογίας αφρωδών)" if spark else "Σάκχαρα",
                               (opts("sugar_level_sparkling") or SPARK_SUGAR) if spark else opts("sugar_level"),
                               f"{p}_sugar_level")
        d["alcohol_level"] = one("Αλκοόλη", opts("alcohol_level"), f"{p}_alcohol_level")
        d["acidity"] = one("Οξύτητα", opts("acidity"), f"{p}_acidity")
        tan = opts("tannins", cat) if cat else []
        if tan:
            d["tannins"] = one("Τανίνες", tan, f"{p}_tannins")
        d["palate_duration"] = one("Διάρκεια", opts("palate_duration"), f"{p}_palate_duration")
        d["aftertaste"] = one("Επίγευση", opts("aftertaste"), f"{p}_aftertaste")
        d["aftertaste_seconds"] = num(st.number_input("Επίγευση σε δευτερόλεπτα (προαιρετικό)", 0, value=None,
                                                      step=1, key=f"{p}_aftertaste_seconds"))
        st.caption(" · ".join(opts("aftertaste_seconds_guide")))
        if spark:
            d["sparkling_texture"] = one("Αφρώδες στο στόμα", opts("sparkling_texture"), f"{p}_sparkling_texture")
        st.button("⬇️ Αντιγραφή αρωμάτων από Μύτη", key=f"{p}_cp_nose",
                  on_click=lambda: st.session_state.update(
                      {f"{p}_palate_aromas_sel": list(st.session_state.get(f"{p}_nose_aromas_sel", []))}))
        picker(f"{p}_palate_aromas", "Αρώματα / γεύσεις στόματος")
        d["palate_aromas"] = "; ".join(st.session_state.get(f"{p}_palate_aromas_sel", []))
        d["palate_comments"] = st.text_area("Σημειώσεις στόματος", key=f"{p}_palate_comments")

    with t[4]:
        d["readiness_state"] = one("Φάση ετοιμότητας", opts("readiness_state"), f"{p}_readiness_state")
        d["food_pairing"] = st.text_input("Συνδυασμός με φαγητό", key=f"{p}_food_pairing")
        d["overall_rating"] = num(st.number_input("Συνολική βαθμολογία (0-5)", 0.0, 5.0, value=None,
                                                  step=0.5, key=f"{p}_overall_rating"))
        if blind:
            d["guess_grape"] = st.text_input("Εκτίμηση: ποικιλία", key=f"{p}_guess_grape")
            d["guess_region_country"] = st.text_input("Εκτίμηση: περιοχή / χώρα", key=f"{p}_guess_region_country")
            d["guess_vintage"] = st.text_input("Εκτίμηση: χρονιά", key=f"{p}_guess_vintage")
        d["notes"] = st.text_area("Επιπλέον σημειώσεις", key=f"{p}_notes")
    return w, d


def save(p, kind, w, d, wid=None, blind=False, final=False):
    S = st.session_state
    if not blind and wid is None and not str(w.get("wine_name", "")).strip():
        st.error("Γράψε το όνομα του κρασιού.")
        return
    if blind and not d.get("blind_sample_number"):
        st.error("Βάλε αριθμό δείγματος.")
        return
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
        if d.get("_photo") is not None and not ids.get("photo"):
            store_photo(book, sid, d["_photo"])
            ids["photo"] = True
        if ids.get("photo"):
            row["photo"] = f"Photos:{sid}"
        upsert(ws, sid, row)
    except Exception as e:
        S[f"{p}_ids"] = ids  # ώστε η επόμενη προσπάθεια να μη δημιουργήσει νέο κρασί
        st.error(f"Σφάλμα αποθήκευσης: {e}")
        return
    ids.update(wid=wid, sid=sid)
    S[f"{p}_ids"] = ids
    load.clear()
    if final:
        S["v_" + kind] += 1  # νέα κενή φόρμα
        S["_flash"] = f"Οριστική καταχώρηση: {sid}"
        st.rerun()
    st.success(f"Προσωρινή αποθήκευση: {sid}. Μπορείς να συνεχίσεις ή να πατήσεις Οριστική καταχώρηση.")


FLOATF, INTF = {"overall_rating", "alcohol_degree", "purchase_price"}, {"aftertaste_seconds", "blind_sample_number"}
SKIP = {"session_id", "wine_id", "tasting_date", "created_at", "is_blind", "photo", "status",
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


# ---------------------------------------------------------------- κύριο πρόγραμμα
S = st.session_state
for n in ("new", "rep", "rev"):
    S.setdefault("v_" + n, 0)  # αλλάζει μετά από οριστική καταχώρηση: νέα κενή φόρμα
pn, pr = f"new{S['v_new']}", f"rep{S['v_rep']}"
if S.get("_flash"):
    st.success(S.pop("_flash"))

st.title("🍷 Ημερολόγιο Κρασιού")
st.caption("Έκδοση κώδικα: 2.1")
tab_new, tab_rep, tab_rev, tab_idx = st.tabs(["➕ Νέα", "🔁 Επανάληψη", "🎭 Αποκάλυψη", "📚 Ευρετήριο"])

with tab_new:
    ses = load("TastingSessions")
    dr = ses[ses["status"] == "Πρόχειρο"] if "status" in ses.columns else ses.iloc[0:0]
    if not dr.empty:
        pk = st.selectbox("📝 Συνέχεια πρόχειρου", dr["session_id"], index=None, key=f"{pn}_dpick",
                          format_func=lambda x: f"{x} · {dr[dr['session_id'] == x].iloc[0]['tasting_date']}")
        if pk:
            st.button("Άνοιγμα πρόχειρου", key=f"{pn}_dopen", on_click=load_draft, args=(pn, pk))
    blind = st.toggle("🕶️ Τυφλή γευσιγνωσία", key=f"{pn}_blind")
    w, d = tasting_ui(pn, blind=blind)
    c1, c2 = st.columns(2)
    if c1.button("💾 Προσωρινή αποθήκευση", key=f"{pn}_sv"):
        save(pn, "new", w, d, blind=blind)
    if c2.button("✅ Οριστική καταχώρηση", type="primary", key=f"{pn}_fin"):
        save(pn, "new", w, d, blind=blind, final=True)

with tab_rep:
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
            c1, c2 = st.columns(2)
            if c1.button("💾 Προσωρινή αποθήκευση", key=f"{pr}_sv"):
                save(pr, "rep", w2, d2, wid=wine["wine_id"])
            if c2.button("✅ Οριστική καταχώρηση", type="primary", key=f"{pr}_fin"):
                save(pr, "rep", w2, d2, wid=wine["wine_id"], final=True)

with tab_rev:
    ses, wines = load("TastingSessions"), load("Wines")
    pend = (ses[(ses["is_blind"] == "Ναι") & (ses["wine_id"].astype(str).str.strip() == "")]
            if "is_blind" in ses.columns else ses.iloc[0:0])
    if pend.empty:
        st.info("Δεν υπάρχουν τυφλές δοκιμές σε αναμονή αποκάλυψης.")
    else:
        pv = f"rv{S['v_rev']}"
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

with tab_idx:
    index_tab()
