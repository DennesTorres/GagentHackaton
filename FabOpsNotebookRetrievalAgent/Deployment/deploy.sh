#!/bin/bash
set -e

# Read staging bucket from local file
if [ ! -f .staging-bucket ]; then
    echo "Error: .staging-bucket file not found in this directory."
    echo "Create it with: echo 'gs://your-bucket-name' > .staging-bucket"
    exit 1
fi
export STAGING_BUCKET=$(cat .staging-bucket)

# Reinstall dependencies if requirements.txt has changed
if [ ! -f .deps-installed ] || [ requirements.txt -nt .deps-installed ]; then
    pip install --upgrade --force-reinstall -r requirements.txt
    touch .deps-installed
fi

# Deploy
if [ -f .resource-name ]; then
    python deploy.py --resource-name "$(cat .resource-name)"
else
    python deploy.py | tee deploy.log
    grep "Deployed resource name:" deploy.log | sed 's/.*: //' > .resource-name
    echo "Saved resource name for future runs."
fi
