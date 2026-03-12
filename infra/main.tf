# infra/main.tf

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

# ---------------------------------------------------------
# 1. PROVIDER
# ---------------------------------------------------------

provider "google" {
  project = var.project_id 
  region  = "us-central1"
  zone    = "us-central1-a"
}

# Enable necessary APIs automatically
resource "google_project_service" "enabled_apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "iam.googleapis.com",
    "artifactregistry.googleapis.com",
    "firestore.googleapis.com", 
    "bigquery.googleapis.com"
  ])
  service            = each.key
  disable_on_destroy = false
}

# ---------------------------------------------------------
# 2. SERVICE ACCOUNTS & IAM
# ---------------------------------------------------------

# Service Account for Cloud Run (The Agents)
resource "google_service_account" "agent_sa" {
  account_id   = "quant-agent-sa"
  display_name = "Quant Agent Cloud Run Service Account"
}

# Allow Scheduler to invoke Cloud Run
resource "google_cloud_run_v2_service_iam_member" "scheduler_invoker" {
  project  = google_cloud_run_v2_service.agent_service.project
  location = google_cloud_run_v2_service.agent_service.location
  name     = google_cloud_run_v2_service.agent_service.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.agent_sa.email}"
}

# ---------------------------------------------------------
# 3. FIRESTORE DATABASE (Serverless State)
# ---------------------------------------------------------

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = "us-central1"
  type        = "FIRESTORE_NATIVE"
}

# ---------------------------------------------------------
# 4. CLOUD RUN (The Agent Engine)
# ---------------------------------------------------------

resource "google_cloud_run_v2_service" "agent_service" {
  name     = "quant-ai-agent-service"
  location = "us-central1"
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      # Replace this with your actual Docker image URI when you build it
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      
      resources {
        limits = {
          cpu    = "1000m"
          memory = "1Gi"
        }
      }
      
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
    }
    
    service_account = google_service_account.agent_sa.email
  }
}

# ---------------------------------------------------------
# 5. CLOUD SCHEDULER (The Triggers)
# ---------------------------------------------------------

# Job A: ACTIVE MODE (Market Hours) - Every 15 mins
resource "google_cloud_scheduler_job" "active_mode" {
  name             = "quant-active-mode-trigger"
  description      = "Triggers agent every 15 mins during US market hours"
  schedule         = "*/15 9-16 * * 1-5" # 9:00 AM to 4:59 PM ET, Mon-Fri
  time_zone        = "America/New_York"
  attempt_deadline = "320s"

  http_target {
    http_method = "POST"
    uri         = google_cloud_run_v2_service.agent_service.uri
    
    body = base64encode("{\"mode\": \"active\"}")

    oidc_token {
      service_account_email = google_service_account.agent_sa.email
    }
  }
}

# Job B: EFFICIENT MODE (Night Shift) - Hourly
resource "google_cloud_scheduler_job" "efficient_mode" {
  name             = "quant-efficient-mode-trigger"
  description      = "Triggers sentinel check hourly outside market hours"
  schedule         = "0 17-23,0-8 * * *" # 5 PM to 8 AM ET
  time_zone        = "America/New_York"
  attempt_deadline = "320s"

  http_target {
    http_method = "POST"
    uri         = google_cloud_run_v2_service.agent_service.uri
    
    body = base64encode("{\"mode\": \"monitoring\"}")

    oidc_token {
      service_account_email = google_service_account.agent_sa.email
    }
  }
}