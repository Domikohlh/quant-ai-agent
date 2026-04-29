# infra/variables.tf

variable "project_id" {
  description = "The GCP Project ID where resources will be deployed"
  type        = string
}

variable "region" {
  description = "The GCP Compute Region (e.g., us-central1)"
  type        = string
  default     = "us-central1"
}

variable "equities_image_tag" {
  description = "The Artifact Registry URI for the equities ingestion image"
  type        = string
  default     = "latest"
}

variable "crypto_image_tag" {
  description = "The Artifact Registry URI for the crypto ingestion image"
  type        = string
  default     = "latest"
}

variable "data_engine_sa_email" {
  description = "The exact email of the service account used for BigQuery ingestion"
  type        = string
}