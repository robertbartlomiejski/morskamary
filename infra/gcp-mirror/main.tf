# infra/gcp-mirror/main.tf
#
# Optional Google Cloud mirror for morskamary CI.
# This Terraform module creates only the Secret Manager containers and
# Cloud Build IAM bindings.  It does NOT store secret values.
#
# Prerequisites
# -------------
# 1. Enable serviceusage.googleapis.com manually once:
#    gcloud services enable serviceusage.googleapis.com --project=<PROJECT_ID>
#
# 2. Authenticate:
#    gcloud auth application-default login
#
# 3. Run:
#    terraform init
#    terraform plan -var="project_id=<PROJECT_ID>"
#    terraform apply -var="project_id=<PROJECT_ID>"
#
# 4. After apply, populate secrets using the bootstrap script — NOT via Terraform:
#    ./scripts/bootstrap_research_secrets.sh --backend gcp --project-id <PROJECT_ID>
#
# This module is entirely optional.  Normal GitHub Actions CI works without it.

terraform {
  required_version = ">= 1.3"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# Derive the Cloud Build service account from the project number
# ---------------------------------------------------------------------------

data "google_project" "project" {
  project_id = var.project_id
}

locals {
  cloudbuild_sa = "${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

# ---------------------------------------------------------------------------
# Enable required APIs
# ---------------------------------------------------------------------------

resource "google_project_service" "apis" {
  for_each = toset([
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "logging.googleapis.com",
    "iam.googleapis.com",
    "serviceusage.googleapis.com",
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# Conditional Artifact Registry API (disabled by default)
resource "google_project_service" "artifact_registry" {
  count   = var.enable_artifact_registry ? 1 : 0
  project = var.project_id
  service = "artifactregistry.googleapis.com"

  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Secret Manager — empty containers only (no secret values in Terraform state)
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "crossref_mailto" {
  project   = var.project_id
  secret_id = "crossref-mailto"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "elsevier_api_key" {
  project   = var.project_id
  secret_id = "elsevier-api-key"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "scopus_api_key" {
  project   = var.project_id
  secret_id = "scopus-api-key"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "wos_api_key" {
  project   = var.project_id
  secret_id = "wos-api-key"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "scival_api_key" {
  project   = var.project_id
  secret_id = "scival-api-key"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# IAM — least-privilege bindings for the Cloud Build service account
# ---------------------------------------------------------------------------

# Secret Manager Secret Accessor on each secret individually
resource "google_secret_manager_secret_iam_member" "cloudbuild_crossref" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.crossref_mailto.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.cloudbuild_sa}"
}

resource "google_secret_manager_secret_iam_member" "cloudbuild_elsevier" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.elsevier_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.cloudbuild_sa}"
}

resource "google_secret_manager_secret_iam_member" "cloudbuild_scopus" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.scopus_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.cloudbuild_sa}"
}

resource "google_secret_manager_secret_iam_member" "cloudbuild_wos" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.wos_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.cloudbuild_sa}"
}

resource "google_secret_manager_secret_iam_member" "cloudbuild_scival" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.scival_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.cloudbuild_sa}"
}

# Logs Writer for Cloud Build
resource "google_project_iam_member" "cloudbuild_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${local.cloudbuild_sa}"
}
