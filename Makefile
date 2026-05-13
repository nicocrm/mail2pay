.PHONY: test requirements.txt build deploy

# Run tests
test:
	uv run pytest

# Export pinned requirements for Scaleway
requirements.txt:
	uv export --no-hashes --format requirements-txt -o requirements.txt

# Build deployment zip: handler.py + mail2pay package + requirements.txt
# Scaleway Serverless Functions (Python) automatically runs `pip install -r
# requirements.txt` from inside the zip at deploy time, so the zip does NOT
# need to bundle the installed site-packages itself.
build: requirements.txt
	@mkdir -p dist
	zip -r dist/mail2pay.zip handler.py mail2pay/ requirements.txt
	@echo "Built dist/mail2pay.zip"

# Deploy to Scaleway (reads creds from .env)
deploy: build
	@set -a && . ./.env && set +a && \
	scw function deploy \
		--namespace-id="$$SCW_NAMESPACE_ID" \
		--zip=dist/mail2pay.zip \
		--handler=handler.handle \
		--runtime=python312 \
		--env-vars="RESEND_API_KEY=$$RESEND_API_KEY,MISTRAL_API_KEY=$$MISTRAL_API_KEY,COMPANY_NAME=$$COMPANY_NAME,FROM_ADDRESS=$$FROM_ADDRESS,LLM_MODEL=$$LLM_MODEL,RESEND_WEBHOOK_SECRET=$$RESEND_WEBHOOK_SECRET"
