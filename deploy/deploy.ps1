param(
  [string]$ProjectId = "project-5e761e8c-65aa-4033-8cb",
  [string]$Region = "europe-west1",
  [string]$FirestoreLocation = "eur3",
  [string]$Model = "gemini-3.7-flash",
  [string]$InternalToken = ""
)

$ErrorActionPreference = "Stop"

function Invoke-Gcloud {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
  & gcloud @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "gcloud command failed with exit code $LASTEXITCODE"
  }
}

function Test-Gcloud {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
  $null = & gcloud @Arguments 2>$null
  return $LASTEXITCODE -eq 0
}

if (-not $InternalToken) {
  $InternalToken = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}

$repository = "origin"
$apiService = "origin-api"
$webService = "origin-web"
$queue = "origin-agent"
$bucket = "$ProjectId-origin-demo"
$runtimeAccount = "origin-runtime@$ProjectId.iam.gserviceaccount.com"
$apiImage = "$Region-docker.pkg.dev/$ProjectId/$repository/origin-api:latest"
$webImage = "$Region-docker.pkg.dev/$ProjectId/$repository/origin-web:latest"

Invoke-Gcloud config set project $ProjectId
Invoke-Gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com firestore.googleapis.com storage.googleapis.com cloudtasks.googleapis.com firebase.googleapis.com

if (-not (Test-Gcloud artifacts repositories describe $repository --location $Region)) {
  Invoke-Gcloud artifacts repositories create $repository --repository-format docker --location $Region
}
if (-not (Test-Gcloud iam service-accounts describe $runtimeAccount)) {
  Invoke-Gcloud iam service-accounts create origin-runtime --display-name "Origin runtime"
}

foreach ($role in @("roles/aiplatform.user", "roles/datastore.user", "roles/storage.objectAdmin", "roles/cloudtasks.enqueuer", "roles/logging.logWriter")) {
  Invoke-Gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$runtimeAccount" --role $role --condition=None
}
Invoke-Gcloud iam service-accounts add-iam-policy-binding $runtimeAccount --member "serviceAccount:$runtimeAccount" --role roles/iam.serviceAccountUser

if (-not (Test-Gcloud firestore databases describe --database "(default)")) {
  Invoke-Gcloud firestore databases create --database "(default)" --location $FirestoreLocation --type firestore-native
}
if (-not (Test-Gcloud storage buckets describe "gs://$bucket")) {
  Invoke-Gcloud storage buckets create "gs://$bucket" --location $Region --uniform-bucket-level-access
}
Invoke-Gcloud storage buckets update "gs://$bucket" --lifecycle-file deploy/gcs-lifecycle.json
if (-not (Test-Gcloud tasks queues describe $queue --location $Region)) {
  Invoke-Gcloud tasks queues create $queue --location $Region --max-dispatches-per-second 5 --max-concurrent-dispatches 5
}

Invoke-Gcloud builds submit apps/api --tag $apiImage
Invoke-Gcloud run deploy $apiService --image $apiImage --region $Region --service-account $runtimeAccount --allow-unauthenticated --min 0 --max 3 --memory 768Mi --cpu 1 --set-env-vars "ORIGIN_GCP_PROJECT=$ProjectId,ORIGIN_VERTEX_LOCATION=global,ORIGIN_GEMINI_MODEL=$Model,ORIGIN_STORE=firestore,ORIGIN_BUCKET=$bucket,ORIGIN_AGENT_DISPATCH=inline,ORIGIN_DEMO_TOKENS=true,ORIGIN_SEED_DEMO=true,ORIGIN_INTERNAL_TOKEN=$InternalToken"
$apiUrl = ([string](Invoke-Gcloud run services describe $apiService --region $Region --format "value(status.url)")).Trim()

Invoke-Gcloud run services update $apiService --region $Region --update-env-vars "ORIGIN_AGENT_DISPATCH=tasks,ORIGIN_TASKS_LOCATION=$Region,ORIGIN_TASKS_QUEUE=$queue,ORIGIN_API_BASE_URL=$apiUrl,ORIGIN_TASK_SERVICE_ACCOUNT=$runtimeAccount"

Invoke-Gcloud builds submit . --config deploy/cloudbuild-web.yaml --substitutions "_API_URL=$apiUrl,_IMAGE=$webImage"
Invoke-Gcloud run deploy $webService --image $webImage --region $Region --allow-unauthenticated --min 0 --max 3 --memory 512Mi --cpu 1
$webUrl = ([string](Invoke-Gcloud run services describe $webService --region $Region --format "value(status.url)")).Trim()
Invoke-Gcloud run services update $apiService --region $Region --update-env-vars "ORIGIN_CORS_ORIGINS=$webUrl"

Write-Output "Origin web: $webUrl"
Write-Output "Origin API: $apiUrl"
Write-Output "Health: $apiUrl/health"
Write-Output "The generated worker token is stored in the Cloud Run environment and was not printed or written to the repository."
