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
# 1. PROVIDER & VARIABLES
# ---------------------------------------------------------

provider "google" {
  project = "quant-ai-agent-482111" # <--- REPLACE THIS
  region  = "us-central1"
  zone    = "us-central1-a"
}

# Enable necessary APIs automatically
resource "google_project_service" "enabled_apis" {
  for_each = toset([
    "compute.googleapis.com",
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
# 2. SERVICE ACCOUNTS
# ---------------------------------------------------------

# Service Account for the VM (IB Gateway & Database)
resource "google_service_account" "vm_sa" {
  account_id   = "quant-vm-sa"
  display_name = "Quant Agent VM Service Account"
}

# Service Account for Cloud Run (The Agents)
resource "google_service_account" "agent_sa" {
  account_id   = "quant-agent-sa"
  display_name = "Quant Agent Cloud Run Service Account"
}

# Allow Scheduler to invoke Cloud Run
resource "google_cloud_run_service_iam_member" "scheduler_invoker" {
  location = google_cloud_run_v2_service.agent_service.location
  name     = google_cloud_run_v2_service.agent_service.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.agent_sa.email}"
}

resource "google_firestore_database" "default" {
  project     = "quant-ai-agent-482111"
  name        = "(default)"
  location_id = "us-central1"
  type        = "FIRESTORE_NATIVE"
}

# ---------------------------------------------------------
# 3. COMPUTE ENGINE (The "Always On" Brain)
# ---------------------------------------------------------
# Cost: ~$14/mo (e2-small). Hosts IB Gateway & SQLite.

resource "google_compute_instance" "ib_gateway_vm" {
  name         = "quant-ib-gateway"
  machine_type = "e2-small"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 20 # GB
    }
  }

  network_interface {
    network = "default"
    access_config {
      # Ephemeral public IP so you can SSH in to install IBKR
    }
  }

  service_account {
    email  = google_service_account.vm_sa.email
    scopes = ["cloud-platform"]
  }

  metadata_startup_script = <<-EOT
    #! /bin/bash
    apt-get update
    apt-get install -y docker.io git
    # Setup for MCP Servers (SQLite) can go here later
  EOT

  tags = ["ib-gateway", "ssh-server"]
}

# Firewall: Allow SSH to the VM
resource "google_compute_firewall" "allow_ssh" {
  name    = "allow-ssh-quant"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"] # WARNING: Limit this to your IP for security later
  target_tags   = ["ssh-server"]
}

# ---------------------------------------------------------
# 4. CLOUD RUN (The Agent Loop)
# ---------------------------------------------------------
# Cost: Pay-per-use. Hosts LangGraph.

resource "google_cloud_run_v2_service" "agent_service" {
  name     = "quant-ai-agent-service"
  location = "us-central1"
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      # PLACEHOLDER IMAGE: Using hello-world initially. 
      # Once you have your Dockerfile ready, you will build and push 
      # your image to GCR, then update this line.
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      
      resources {
        limits = {
          cpu    = "1000m"
          memory = "1Gi"
        }
      }
      
      env {
        name  = "GCP_PROJECT_ID"
        value = "YOUR_PROJECT_ID"
      }
      # Add other ENV vars here (API Keys should go in Secret Manager ideally)
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
    
    # Body payload tells the agent which mode to run
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
