# infra/gcp-mirror/outputs.tf
#
# Outputs suitable for use in cloudbuild.yaml availableSecrets.versionName fields.
# These paths reference the latest version of each secret, which must be
# created manually via the bootstrap script (not via Terraform).

output "secret_version_names" {
  description = "Map of secret names to their latest-version paths for use in cloudbuild.yaml."
  value = {
    crossref_mailto  = "${google_secret_manager_secret.crossref_mailto.name}/versions/latest"
    elsevier_api_key = "${google_secret_manager_secret.elsevier_api_key.name}/versions/latest"
    scopus_api_key   = "${google_secret_manager_secret.scopus_api_key.name}/versions/latest"
    wos_api_key      = "${google_secret_manager_secret.wos_api_key.name}/versions/latest"
    scival_api_key   = "${google_secret_manager_secret.scival_api_key.name}/versions/latest"
  }
}

output "cloudbuild_service_account" {
  description = "Cloud Build service account email (derived from project number)."
  value       = local.cloudbuild_sa
}

output "project_number" {
  description = "Numeric Google Cloud project number."
  value       = data.google_project.project.number
}

output "region" {
  description = "Region used for secret replication and Cloud Build."
  value       = var.region
}
