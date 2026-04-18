# 1. Define variables
PROJECT_ID="your-project-id"
# SA_NAME="your-service-account-name"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
# NEW_SA_NAME="new-service-account-name"
# NEW_SA_EMAIL="${NEW_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# 2. Create the new service account
# gcloud iam service-accounts create $NEW_SA_NAME \
#     --description="Recreated service account" \
#     --display-name="$NEW_SA_NAME"

# 3. List and apply project-level IAM roles from the old SA to the new one
# This command finds roles held by the old SA and grants them to the new one
gcloud projects get-iam-policy $PROJECT_ID \
    --flatten="bindings[].members" \
    --format='table(bindings.role)' \
    --filter="bindings.members:$SA_EMAIL" #| grep -v ROLE | while read ROLE; do
    # gcloud projects add-iam-policy-binding $PROJECT_ID \
    #     --member="serviceAccount:$NEW_SA_EMAIL" \
    #     --role="$ROLE"
# done

# 4. Optional: Export Service Account Keys (if keys were used)
# Note: You cannot export the private key of an existing SA.
# You must create a new key for the new service account.
# gcloud iam service-accounts keys create ${NEW_SA_NAME}-key.json \
#     --iam-account=$NEW_SA_EMAIL

#   ------------------------------------------------------------------  #
#   ------------------------------------------------------------------  #
#   ------------------------------------------------------------------  #

ROLE
roles/artifactregistry.writer
roles/editor
roles/iam.serviceAccountUser
roles/logging.logWriter
roles/run.admin
roles/run.invoker