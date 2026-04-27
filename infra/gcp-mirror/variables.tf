# infra/gcp-mirror/variables.tf

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
