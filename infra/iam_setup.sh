#!/usr/bin/env bash
# Least-privilege service account for the Socraitia backend Cloud Run service.
#
# Roles, and why each one exists (this is the Architectural Discipline note):
#   roles/datastore.user     — read/write Firestore `socraitia` (graph, sessions, feed)
#   roles/aiplatform.user    — Gemini 3.5, embeddings, (later) Veo
#   roles/pubsub.publisher   — Cartographer publishes new claims to claims-to-verify
#   roles/pubsub.subscriber  — the Verifier push/pull path on the same service
#   roles/storage.objectAdmin — Veo recap objects, Phase 6; granted now so the
#                               deploy does not grow a second IAM pass
#
# The Cloud Run *runtime* identity is this account. Cloud Build still uses the
# project's Cloud Build service account to build and deploy the image.
#
#   ./infra/iam_setup.sh

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-socraitia}"
SA_NAME="socraitia-backend"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT}" >/dev/null

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  pubsub.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  --quiet

if ! gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="Socraitia backend (Cloud Run)" \
    --description="Least-privilege runtime identity for socraitia-api"
fi

for ROLE in \
  roles/datastore.user \
  roles/aiplatform.user \
  roles/pubsub.publisher \
  roles/pubsub.subscriber \
  roles/storage.objectAdmin
do
  gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None \
    --quiet >/dev/null
  echo "granted ${ROLE} → ${SA_EMAIL}"
done

echo
echo "runtime service account: ${SA_EMAIL}"
