# infra/main.tf
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "7.23.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# =====================================================================
# COMMON RESOURCES (Shared across pipelines)
# =====================================================================

# The service account used purely by Cloud Scheduler to click the "Run" button
# We keep this entirely separate from the BigQuery data ingestion identity.
resource "google_service_account" "scheduler_trigger_sa" {
  account_id   = "scheduler-trigger-sa"
  display_name = "Cloud Scheduler Trigger SA"
}

# =====================================================================
# PIPELINE 1: EQUITIES (DAILY)
# =====================================================================

resource "google_cloud_run_v2_job" "equities_job" {
  name     = "quant-daily-ingestion"
  location = var.region

  template {
    template {
      # Direct variable reference to your existing Service Account
      service_account = var.data_engine_sa_email

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/quant-repo/daily-ingestion:${var.equities_image_tag}"

        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }

        env {
          name  = "GCP_COMPUTE_REGION"
          value = var.region
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
      timeout = "1800s" # 30 mins
    }
  }
}

resource "google_cloud_run_v2_job_iam_member" "equities_scheduler_invoker" {
  project  = google_cloud_run_v2_job.equities_job.project
  location = google_cloud_run_v2_job.equities_job.location
  name     = google_cloud_run_v2_job.equities_job.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_trigger_sa.email}"
}

resource "google_cloud_scheduler_job" "equities_scheduler" {
  name        = "trigger-daily-ingestion"
  description = "Runs M-F at 6:00 PM NYC time"
  schedule    = "0 18 * * 1-5"
  time_zone   = "America/New_York"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.equities_job.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_trigger_sa.email
    }
  }
  depends_on = [google_cloud_run_v2_job_iam_member.equities_scheduler_invoker]
}

# =====================================================================
# PIPELINE 2: CRYPTO (HOURLY)
# =====================================================================

resource "google_cloud_run_v2_job" "crypto_job" {
  name     = "quant-crypto-hourly-ingestion"
  location = var.region

  template {
    template {
      # Reusing the exact same identity for BigQuery write access
      service_account = var.data_engine_sa_email

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/quant-repo/crypto-ingestion:${var.crypto_image_tag}"

        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }

        env {
          name  = "GCP_COMPUTE_REGION"
          value = var.region
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
      timeout = "600s" # 10 mins
    }
  }
}

resource "google_cloud_run_v2_job_iam_member" "crypto_scheduler_invoker" {
  project  = google_cloud_run_v2_job.crypto_job.project
  location = google_cloud_run_v2_job.crypto_job.location
  name     = google_cloud_run_v2_job.crypto_job.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_trigger_sa.email}"
}

resource "google_cloud_scheduler_job" "crypto_scheduler" {
  name        = "trigger-hourly-crypto-ingestion"
  description = "Runs at minute 2 of every hour"
  schedule    = "2 * * * *"
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.crypto_job.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_trigger_sa.email
    }
  }
  depends_on = [google_cloud_run_v2_job_iam_member.crypto_scheduler_invoker]
}

# =====================================================================
# PIPELINE 3: MCP server 
# =====================================================================
resource "google_cloud_run_v2_service" "mcp_server" {
  name     = "quant-mcp-server"
  location = var.region

  template {
    # CRITICAL: Gen 2 provides native Linux compatibility and faster CPU for Pandas/NumPy
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
    
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/quant-repo/mcp-server:latest"
      
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      
      resources {
        limits = {
          cpu    = "2"      # Backtesting needs dedicated compute
          memory = "4Gi"    # Loading 3 years of hourly BQ data requires RAM
        }
      }
    }
    
    # We must limit concurrency. If 10 agents hit the backtester at once, 
    # it will OOM crash. Force Cloud Run to scale horizontally instead.
    max_instance_request_concurrency = 4
  }
}

# Generate a URL, but keep it locked down (do not use roles/run.invoker for allUsers)