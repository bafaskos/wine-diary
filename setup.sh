mkdir -p ~/.streamlit/
echo "\
[gcp_service_account]
type = \"${GCP_TYPE}\"
project_id = \"${GCP_PROJECT_ID}\"
private_key_id = \"${GCP_PRIVATE_KEY_ID}\"
private_key = \"${GCP_PRIVATE_KEY}\"
client_email = \"${GCP_CLIENT_EMAIL}\"
client_id = \"${GCP_CLIENT_ID}\"
auth_uri = \"${GCP_AUTH_URI}\"
token_uri = \"${GCP_TOKEN_URI}\"
auth_provider_x509_cert_url = \"${GCP_AUTH_PROVIDER_X509_CERT_URL}\"
client_x509_cert_url = \"${GCP_CLIENT_X509_CERT_URL}\"
universe_domain = \"${GCP_UNIVERSE_DOMAIN}\"
" > ~/.streamlit/secrets.toml

# Δημιουργία του credentials.json αυτόματα από τα Secrets για να διαβάζει ο κώδικας
python3 -c '
import streamlit as st, json
secrets = dict(st.secrets["gcp_service_account"])
with open("credentials.json", "w") as f:
    json.dump(secrets, f)
'
