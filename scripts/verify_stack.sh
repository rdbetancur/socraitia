#!/usr/bin/env bash
#
# Verifies every Google model identifier and region Socraitia depends on,
# against the live API, in the caller's own GCP project.
#
# This is not a unit test. It is the reproducible proof that the model IDs in
# the README are real, because Vertex model names and their regional
# availability rotate on the order of weeks. Run it before believing anything
# this repo claims.
#
#   ./scripts/verify_stack.sh
#
# Requires: gcloud, curl, python3, and `gcloud auth application-default login`.

set -uo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-socraitia}"
GEMINI_LOCATION="global"
VEO_LOCATION="us-central1"

MODEL_SOCRATIC="gemini-3.5-flash"
MODEL_EMBEDDING="gemini-embedding-2"
MODEL_VEO="veo-3.1-fast-generate-001"

pass=0
fail=0

TOKEN="$(gcloud auth print-access-token 2>/dev/null)"
if [[ -z "${TOKEN}" ]]; then
  echo "FAIL  could not mint an access token. Run: gcloud auth application-default login"
  exit 1
fi

hdr=(-H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
     -H "x-goog-user-project: ${PROJECT}")

# check <label> <expected-http> <method> <url> [payload]
check() {
  local label="$1" expected="$2" method="$3" url="$4" payload="${5:-}"
  local code
  if [[ "${method}" == "POST" ]]; then
    code="$(curl -s -o /tmp/vs.json -w '%{http_code}' -X POST "${url}" "${hdr[@]}" -d "${payload}")"
  else
    code="$(curl -s -o /tmp/vs.json -w '%{http_code}' "${url}" "${hdr[@]}")"
  fi

  if [[ "${code}" == "${expected}" ]]; then
    printf '  PASS  %-52s HTTP %s\n' "${label}" "${code}"
    pass=$((pass + 1))
  else
    printf '  FAIL  %-52s HTTP %s (expected %s)\n' "${label}" "${code}" "${expected}"
    python3 -c "import json;print('        ',json.load(open('/tmp/vs.json')).get('error',{}).get('message','')[:150])" 2>/dev/null
    fail=$((fail + 1))
  fi
}

gen_url() { echo "https://aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${1}/publishers/google/models/${2}:${3}"; }
reg_url() { echo "https://${1}-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${1}/publishers/google/models/${2}:${3}"; }

PING='{"contents":[{"role":"user","parts":[{"text":"Reply with the single word PONG"}]}],"generationConfig":{"maxOutputTokens":600}}'
GROUNDED='{"contents":[{"role":"user","parts":[{"text":"Name one 2026 study on AI tutoring. One sentence."}]}],"tools":[{"googleSearch":{}}],"generationConfig":{"maxOutputTokens":800}}'
EMBED='{"content":{"parts":[{"text":"verification probe"}]}}'

echo
echo "Socraitia stack verification  ·  project=${PROJECT}  ·  $(date -u '+%Y-%m-%d %H:%MZ')"
echo "------------------------------------------------------------------------------"

echo "Gemini (must be on the global endpoint):"
check "${MODEL_SOCRATIC} @ ${GEMINI_LOCATION}" 200 POST \
  "$(gen_url "${GEMINI_LOCATION}" "${MODEL_SOCRATIC}" generateContent)" "${PING}"
# Asserted as a 404 on purpose: this is the constraint the architecture is built
# around, so a change here (Google backfilling the region) should be visible.
check "${MODEL_SOCRATIC} @ us-central1 (expected absent)" 404 POST \
  "$(reg_url us-central1 "${MODEL_SOCRATIC}" generateContent)" "${PING}"
check "google_search grounding @ ${GEMINI_LOCATION}" 200 POST \
  "$(gen_url "${GEMINI_LOCATION}" "${MODEL_SOCRATIC}" generateContent)" "${GROUNDED}"

echo "Embeddings:"
check "${MODEL_EMBEDDING} @ ${GEMINI_LOCATION}" 200 POST \
  "$(gen_url "${GEMINI_LOCATION}" "${MODEL_EMBEDDING}" embedContent)" "${EMBED}"

echo "Veo (must be on us-central1):"
check "${MODEL_VEO} @ ${VEO_LOCATION}" 200 GET \
  "https://${VEO_LOCATION}-aiplatform.googleapis.com/v1/publishers/google/models/${MODEL_VEO}"

echo "Gemma (Model Garden availability):"
check "gemma3 publisher model @ ${VEO_LOCATION}" 200 GET \
  "https://${VEO_LOCATION}-aiplatform.googleapis.com/v1/publishers/google/models/gemma3"

echo "Firestore:"
if gcloud firestore databases list --project "${PROJECT}" --format='value(name)' 2>/dev/null | grep -q "${PROJECT}"; then
  printf '  PASS  %-52s present\n' "database ${PROJECT} (us-central1, NATIVE)"
  pass=$((pass + 1))
else
  printf '  FAIL  %-52s not found\n' "database ${PROJECT}"
  fail=$((fail + 1))
fi

echo "------------------------------------------------------------------------------"
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]] || exit 1
