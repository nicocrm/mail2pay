.PHONY: test requirements.txt build create deploy

PYTHON_VERSION=3.12

# Run tests
test:
	uv run pytest

# Export pinned requirements for Scaleway
requirements.txt:
	uv export --no-dev --no-hashes --format requirements-txt -o requirements.txt

# Build deployment zip: handler.py + mail2pay package + requirements.txt + dependencies
# Scaleway build pipeline does NOT automatically get dependencies for us
build: requirements.txt
	@rm -rf dist
	@mkdir -p dist
	# docker run --rm -v $(CURDIR):/home/app/function \
	# 	--workdir /home/app/function rg.fr-par.scw.cloud/scwfunctionsruntimes-public/python-dep:$(PYTHON_VERSION) \
	# 	pip install -r requirements.txt --target ./dist/package
	uv pip install \
		--no-installer-metadata \
		--no-compile-bytecode \
		--python-platform x86_64-unknown-linux-musl \
		--python 3.12 \
		--target dist/package \
		-r requirements.txt
	zip -r dist/mail2pay.zip handler.py mail2pay/
	cd dist && zip -r mail2pay.zip package
	@echo "Built dist/mail2pay.zip"

# # One-time: create the function 
# create:
# 	@set -a && . ./.env && set +a && \
# 	scw function function create \
# 		name=webhook.handler \
# 		runtime=python312 \
# 		handler=handler.handle \
# 		privacy=public \
# 		env-vars="RESEND_API_KEY=$$RESEND_API_KEY,MISTRAL_API_KEY=$$MISTRAL_API_KEY,FROM_ADDRESS=$$FROM_ADDRESS,LLM_MODEL=$$LLM_MODEL,RESEND_WEBHOOK_SECRET=$$RESEND_WEBHOOK_SECRET"

# Deploy to Scaleway (reads creds from .env). Assumes `make create` has been run.
function-update:
	@set -a && . ./.env && set +a && \
	scw function function update \
		$$SCW_FUNCTION_ID \
		handler=handler.handle \
		redeploy=true \
		secret-environment-variables.0.key=RESEND_API_KEY \
		secret-environment-variables.0.value=$$RESEND_API_KEY \
		secret-environment-variables.1.key=MISTRAL_API_KEY \
		secret-environment-variables.1.value=$$MISTRAL_API_KEY \
		environment-variables.FROM_ADDRESS=$$FROM_ADDRESS \
		environment-variables.LLM_MODEL=$$LLM_MODEL \
		environment-variables.RESEND_API_KEY=$$RESEND_API_KEY \
		environment-variables.RESEND_WEBHOOK_SECRET=$$RESEND_WEBHOOK_SECRET

function-deploy: build
	@set -a && . ./.env && set +a && \
	scw function deploy \
		name=mail2pay-webhook \
		namespace-id=$$SCW_NAMESPACE_ID \
		runtime=python312 \
		zip-file=dist/mail2pay.zip

deploy: function-deploy function-update
