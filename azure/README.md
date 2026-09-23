# Azure Pilot Mapping

Local -> Azure:
- Streamlit -> Azure Container Apps
- PostgreSQL -> Azure Database for PostgreSQL
- SEC raw documents -> Azure Blob Storage
- Scheduled ETL -> Azure Functions / Container Apps Jobs
- Secrets -> Azure Key Vault
- Monitoring -> Application Insights
- CI/CD -> GitHub Actions

Move to Azure only after the local MVP is reproducible and walk-forward evaluation is passing.
