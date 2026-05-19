# infra/gcp-mirror/variables.tf

variable "cloudbuild_service_account_email" {
  description = <<-EOT
    Email address of the Cloud Build service account to grant Secret Manager
    access and log-writing permissions.

    Leave empty (default) to use the legacy Cloud Build service account derived
    automatically from the project number:
      <project_number>@cloudbuild.gserviceaccount.com

    Set this variable if your project uses a custom Cloud Build service account
    (common in newer GCP setups or when using Workload Identity Federation).
    Example: "my-cb-sa@my-project.iam.gserviceaccount.com"
  EOT
  type    = string
  default = ""
}

variable "project_id" {
  description = "Google Cloud project ID (e.g. intricate-shard-477117-f7)."
  type        = string
}

variable "region" {
  description = "Google Cloud region for Secret Manager replication and Cloud Build."
  type        = string
  default     = "europe-west1"
}

variable "github_owner" {
  description = "GitHub repository owner (for optional Cloud Build trigger configuration)."
  type        = string
  default     = "robertbartlomiejski"
}

variable "github_repo" {
  description = "GitHub repository name (for optional Cloud Build trigger configuration)."
  type        = string
  default     = "morskamary"
}

variable "github_connection_name" {
  description = <<-EOT
    Name of the Cloud Build GitHub connection resource.
    Note: GitHub connections require OAuth consent via the Cloud Console before
    Terraform can manage triggers. Create the connection manually first if needed.
    See docs/GOOGLE_CLOUD_BUILD_OPTIONAL_SETUP.md for instructions.
  EOT
  type        = string
  default     = "morskamary-github"
}

variable "enable_artifact_registry" {
  description = "Set to true to enable Artifact Registry API (needed only if building container images)."
  type        = bool
  default     = false
}
