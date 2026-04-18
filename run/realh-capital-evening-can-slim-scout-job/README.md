# realh-capital
# realh-capital-evening-can-slim-scout-job

# cloud run config
Service Name: realh-capital-evening-can-slim-scout-job
Region: us-central1 (Iowa)
Runtime: Python 3.14
Authentication: Require Authentication
    Identity and Access Management (IAM)
Billing: Request Based
Service Scaling: Auto scaling
    Minimum number of instances: 0
    Maximum number of instances: 1
Ingress: Internal
Containers > Resources > Memory: 1 Gib
Request timeout: 540

Function entry point: realh_capital_evening_can_slim_scout_job