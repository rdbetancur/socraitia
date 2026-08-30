#!/usr/bin/env bash
# Deploy both Cloud Run services and wire Pub/Sub push.
#
# Order is forced: backend first (so we have a public URL), frontend second
# with that URL baked in at Docker build time. NEXT_PUBLIC_* is inlined by
# Next.js at `next build`, not read at runtime — a runtime env var on the
# frontend service would be silently ignored.
#
#   ./infra/iam_setup.sh
#   ./infra/deploy.sh

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-socraitia}"
REGION="${CLOUD_RUN_REGION:-us-central1}"
SA_EMAIL="socraitia-backend@${PROJECT}.iam.gserviceaccount.com"
PUSH_TOKEN="${PUBSUB_PUSH_TOKEN:-socraitia-push-2026}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

gcloud config set project "${PROJECT}" >/dev/null

echo "==> backend → Cloud Run (us-central1)"
gcloud run deploy socraitia-api \
  --source "${ROOT}/backend" \
  --region "${REGION}" \
  --service-account "${SA_EMAIL}" \
  --allow-unauthenticated \
  --quiet \
  --timeout=300 \
  --cpu=2 \
  --memory=2Gi \
  --min-instances=1 \
  --max-instances=4 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=global,FIRESTORE_DATABASE=socraitia,GEMINI_LOCATION=global,VEO_LOCATION=us-central1,CORS_ORIGINS=*,PUBSUB_CLAIMS_TOPIC=claims-to-verify,PUBSUB_PUSH_TOKEN=${PUSH_TOKEN},ENABLE_VERIFIER=true,ENABLE_EMBEDDINGS=true"

API_URL="$(gcloud run services describe socraitia-api --region "${REGION}" --format='value(status.url)')"
echo "backend URL: ${API_URL}"

echo "==> Pub/Sub topics + push subscriptions"
gcloud pubsub topics create claims-to-verify --quiet 2>/dev/null || true
gcloud pubsub subscriptions delete claims-to-verify-push --quiet 2>/dev/null || true
gcloud pubsub subscriptions create claims-to-verify-push \
  --topic=claims-to-verify \
  --push-endpoint="${API_URL}/internal/pubsub/claims?token=${PUSH_TOKEN}" \
  --ack-deadline=180 \
  --quiet

gcloud pubsub topics create documents-to-ingest --quiet 2>/dev/null || true
gcloud pubsub subscriptions delete documents-to-ingest-push --quiet 2>/dev/null || true
gcloud pubsub subscriptions create documents-to-ingest-push \
  --topic=documents-to-ingest \
  --push-endpoint="${API_URL}/internal/pubsub/ingest?token=${PUSH_TOKEN}" \
  --ack-deadline=300 \
  --quiet

echo "==> GCS ingest bucket"
gcloud storage buckets create "gs://${PROJECT}-ingest" \
  --location="${REGION}" --quiet 2>/dev/null || true

echo "==> frontend → Cloud Run (build-arg NEXT_PUBLIC_API_URL)"
# Cloud Run --source does not forward Docker ARGs. Build the image ourselves
# so NEXT_PUBLIC_API_URL is actually in the client bundle.
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/socraitia/web"
gcloud artifacts repositories create socraitia \
  --repository-format=docker \
  --location="${REGION}" \
  --quiet 2>/dev/null || true
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
gcloud artifacts repositories add-iam-policy-binding socraitia \
  --location="${REGION}" \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role=roles/artifactregistry.writer \
  --quiet >/dev/null || true
gcloud builds submit "${ROOT}/frontend" \
  --config="${ROOT}/infra/frontend.cloudbuild.yaml" \
  --substitutions="_API_URL=${API_URL},_IMAGE=${IMAGE}"

gcloud run deploy socraitia-web \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --quiet \
  --timeout=60 \
  --cpu=1 \
  --memory=512Mi \
  --min-instances=0 \
  --max-instances=3

WEB_URL="$(gcloud run services describe socraitia-web --region "${REGION}" --format='value(status.url)')"
echo
echo "frontend: ${WEB_URL}"
echo "backend:  ${API_URL}"
echo "health:   ${API_URL}/health"
