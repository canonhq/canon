"""Helm chart template rendering tests.

Validates that each deployment profile (default, production, preview, OIDC,
Zitadel) renders correct Kubernetes manifests from the chart at ``chart/canon/``.
"""

from __future__ import annotations

import shutil

import pytest

from tests.helpers.helm import find_all_manifests, find_manifest, helm_template

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None,
    reason="helm CLI not installed",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env_from_names(manifest: dict) -> list[str]:
    """Return all envFrom secretRef / configMapRef names from a Deployment."""
    names: list[str] = []
    containers = manifest.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    for container in containers:
        for ref in container.get("envFrom", []):
            if "secretRef" in ref:
                names.append(ref["secretRef"]["name"])
            if "configMapRef" in ref:
                names.append(ref["configMapRef"]["name"])
    return names


def _configmap_data(manifests: list[dict]) -> dict[str, str]:
    """Return the ``data`` dict from the first ConfigMap manifest."""
    cm = find_manifest(manifests, kind="ConfigMap")
    assert cm is not None, "Expected a ConfigMap manifest"
    return cm.get("data", {})


# ---------------------------------------------------------------------------
# TestDefaultValues
# ---------------------------------------------------------------------------


class TestDefaultValues:
    """Render with only the base ``values.yaml`` (no overlay)."""

    @pytest.fixture(autouse=True)
    def manifests(self):
        self._manifests = helm_template()

    def test_renders_without_errors(self):
        assert len(self._manifests) > 0

    def test_deployment_exists(self):
        dep = find_manifest(self._manifests, kind="Deployment")
        assert dep is not None, "Expected a Deployment manifest"

    def test_service_exists(self):
        svc = find_manifest(self._manifests, kind="Service")
        assert svc is not None, "Expected a Service manifest"

    def test_no_ingress_by_default(self):
        ing = find_manifest(self._manifests, kind="Ingress")
        assert ing is None, "Ingress should not be rendered when ingress.enabled=false"

    def test_cronjob_enabled_by_default(self):
        crons = find_all_manifests(self._manifests, kind="CronJob")
        assert len(crons) >= 1, "At least the reverse-sync CronJob should exist"
        # The default sync cronjob should be present
        sync_cron = find_manifest(self._manifests, kind="CronJob", name="canon-sync")
        assert sync_cron is not None, "Expected canon-sync CronJob"

    def test_no_auth0_secret_without_config(self):
        """No Auth0 Secret should be created when auth0 values are empty."""
        secrets = find_all_manifests(self._manifests, kind="Secret")
        auth0_secrets = [s for s in secrets if "auth0" in s.get("metadata", {}).get("name", "")]
        assert len(auth0_secrets) == 0, "Auth0 Secret should not be created with empty auth0 values"

    def test_no_oidc_secret_without_config(self):
        """No OIDC Secret should be created when oidc values are empty."""
        secrets = find_all_manifests(self._manifests, kind="Secret")
        oidc_secrets = [s for s in secrets if "oidc" in s.get("metadata", {}).get("name", "")]
        assert len(oidc_secrets) == 0, "OIDC Secret should not be created with empty oidc values"

    def test_no_stripe_secret_without_config(self):
        """No Stripe Secret should be created when stripe values are empty."""
        secrets = find_all_manifests(self._manifests, kind="Secret")
        stripe_secrets = [s for s in secrets if "stripe" in s.get("metadata", {}).get("name", "")]
        assert len(stripe_secrets) == 0, (
            "Stripe Secret should not be created with empty stripe values"
        )

    def test_no_smtp_secret_without_config(self):
        """No SMTP Secret should be created when smtp values are empty."""
        secrets = find_all_manifests(self._manifests, kind="Secret")
        smtp_secrets = [s for s in secrets if "smtp" in s.get("metadata", {}).get("name", "")]
        assert len(smtp_secrets) == 0, "SMTP Secret should not be created with empty smtp values"

    def test_profile_hub_disabled_by_default(self):
        """T13 — OSS / self-hosted default ships with the hub gated off."""
        data = _configmap_data(self._manifests)
        assert data.get("PROFILE_HUB_ENABLED") == "false", (
            "Profile hub must default OFF in the base chart so a fresh "
            "OSS deploy doesn't expose self-serve delete + email-change "
            "UI before the operator has vetted them. Got "
            f"{data.get('PROFILE_HUB_ENABLED')!r}"
        )


# ---------------------------------------------------------------------------
# TestProductionValues
# ---------------------------------------------------------------------------


class TestProductionValues:
    """Render with ``-f values-production.yaml``."""

    @pytest.fixture(autouse=True)
    def manifests(self):
        self._manifests = helm_template("chart/canon/values-production.yaml")

    def test_renders_without_errors(self):
        assert len(self._manifests) > 0

    def test_ingress_enabled(self):
        ing = find_manifest(self._manifests, kind="Ingress")
        assert ing is not None, "Expected an Ingress manifest in production"
        rules = ing.get("spec", {}).get("rules", [])
        assert len(rules) > 0
        assert rules[0]["host"] == "canonhq.co"

    def test_auth0_existing_secret_referenced(self):
        """Deployment envFrom should include the ``canon-auth0`` secret."""
        dep = find_manifest(self._manifests, kind="Deployment")
        assert dep is not None
        names = _env_from_names(dep)
        assert "canon-auth0" in names, f"Expected 'canon-auth0' in envFrom refs, got {names}"

    def test_reindex_cronjob_enabled(self):
        crons = find_all_manifests(self._manifests, kind="CronJob")
        reindex = [c for c in crons if "reindex" in c.get("metadata", {}).get("name", "")]
        assert len(reindex) == 1, "Expected exactly one reindex CronJob"

    def test_production_environment(self):
        """ConfigMap should set ENVIRONMENT=production."""
        data = _configmap_data(self._manifests)
        assert data.get("ENVIRONMENT") == "production", (
            f"Expected ENVIRONMENT=production, got {data.get('ENVIRONMENT')!r}"
        )

    def test_profile_hub_enabled_in_production(self):
        """T13 — production overlay flips the Profile & Account hub on.

        If this assertion ever fails, the gated tabs (Account, Security,
        Notifications, Preferences, Linked, Danger) silently disappear
        from the UI in prod with no other signal. The default-off case
        is covered separately in TestDefaultValues so we know the OSS
        chart still ships gated.
        """
        data = _configmap_data(self._manifests)
        assert data.get("PROFILE_HUB_ENABLED") == "true", (
            "Profile hub must be ON in production — T13 of "
            "profile-account-management. Got "
            f"{data.get('PROFILE_HUB_ENABLED')!r}"
        )


# ---------------------------------------------------------------------------
# TestPreviewValues
# ---------------------------------------------------------------------------


class TestPreviewValues:
    """Render with production + preview overlays and per-PR set values."""

    @pytest.fixture(autouse=True)
    def manifests(self):
        self._manifests = helm_template(
            "chart/canon/values-production.yaml",
            "chart/canon/values-preview.yaml",
            set_values={
                "ingress.hostname": "pr-99.canonhq.co",
                "config.platformUrl": "https://pr-99.canonhq.co",
            },
        )

    def test_renders_without_errors(self):
        assert len(self._manifests) > 0

    def test_all_cronjobs_disabled(self):
        crons = find_all_manifests(self._manifests, kind="CronJob")
        assert len(crons) == 0, f"Expected no CronJob manifests in preview, got {len(crons)}"

    def test_preview_environment(self):
        """ConfigMap should set ENVIRONMENT=preview."""
        data = _configmap_data(self._manifests)
        assert data.get("ENVIRONMENT") == "preview", (
            f"Expected ENVIRONMENT=preview, got {data.get('ENVIRONMENT')!r}"
        )

    def test_ingress_hostname(self):
        ing = find_manifest(self._manifests, kind="Ingress")
        assert ing is not None, "Expected an Ingress manifest in preview"
        rules = ing.get("spec", {}).get("rules", [])
        assert len(rules) > 0
        assert rules[0]["host"] == "pr-99.canonhq.co"


# ---------------------------------------------------------------------------
# TestOIDCConfiguration
# ---------------------------------------------------------------------------


class TestOIDCConfiguration:
    """OIDC secret rendering for generic OIDC providers (OSS deployment)."""

    def test_oidc_secret_created(self):
        """When issuer + clientId + clientSecret are set, an OIDC Secret is created."""
        manifests = helm_template(
            set_values={
                "secrets.oidc.issuer": "https://idp.example.com",
                "secrets.oidc.clientId": "test-cid",
                "secrets.oidc.clientSecret": "test-csec",
            },
        )
        secrets = find_all_manifests(manifests, kind="Secret")
        oidc_secrets = [s for s in secrets if "oidc" in s.get("metadata", {}).get("name", "")]
        assert len(oidc_secrets) == 1, "Expected exactly one OIDC Secret"
        string_data = oidc_secrets[0].get("stringData", {})
        assert string_data.get("OIDC_ISSUER") == "https://idp.example.com"
        assert string_data.get("OIDC_CLIENT_ID") == "test-cid"
        assert string_data.get("OIDC_CLIENT_SECRET") == "test-csec"

    def test_oidc_secret_not_created_with_existing_secret(self):
        """When existingSecret is set, no OIDC Secret is rendered."""
        manifests = helm_template(
            set_values={
                "secrets.oidc.existingSecret": "my-oidc",
            },
        )
        secrets = find_all_manifests(manifests, kind="Secret")
        oidc_secrets = [s for s in secrets if "oidc" in s.get("metadata", {}).get("name", "")]
        assert len(oidc_secrets) == 0, (
            "OIDC Secret should not be created when existingSecret is set"
        )

    def test_deployment_mounts_oidc_secret(self):
        """Deployment envFrom should reference the OIDC secret."""
        manifests = helm_template(
            set_values={
                "secrets.oidc.issuer": "https://idp.example.com",
                "secrets.oidc.clientId": "test-cid",
                "secrets.oidc.clientSecret": "test-csec",
            },
        )
        dep = find_manifest(manifests, kind="Deployment")
        assert dep is not None
        names = _env_from_names(dep)
        oidc_refs = [n for n in names if "oidc" in n]
        assert len(oidc_refs) >= 1, f"Expected OIDC secret ref in envFrom, got {names}"

    def test_oidc_secret_not_mounted_without_full_credentials(self):
        """Deployment should NOT mount OIDC secret when only issuer is set (no clientId/clientSecret)."""
        manifests = helm_template(
            set_values={
                "secrets.oidc.issuer": "https://idp.example.com",
            },
        )
        dep = find_manifest(manifests, kind="Deployment")
        assert dep is not None
        names = _env_from_names(dep)
        oidc_refs = [n for n in names if "oidc" in n]
        assert len(oidc_refs) == 0, (
            f"OIDC secret should not be mounted without full credentials, got {names}"
        )


# ---------------------------------------------------------------------------
# TestZitadelSubchart
# ---------------------------------------------------------------------------


class TestZitadelSubchart:
    """Zitadel bundled identity provider rendering."""

    def test_no_zitadel_by_default(self):
        """No Zitadel resources when zitadel.enabled=false (default)."""
        manifests = helm_template()
        jobs = find_all_manifests(manifests, kind="Job")
        zitadel_jobs = [j for j in jobs if "zitadel" in j.get("metadata", {}).get("name", "")]
        assert len(zitadel_jobs) == 0, "No Zitadel Job should exist when zitadel.enabled=false"

    def test_zitadel_setup_job_exists(self):
        """When zitadel.enabled=true and setup=true, a zitadel-setup Job exists."""
        manifests = helm_template(
            set_values={
                "zitadel.enabled": "true",
                "zitadel.setup": "true",
                # Zitadel subchart has a nested zitadel: key in its own values
                "zitadel.zitadel.masterkey": "test-master-key-32-chars-long-xx",
                "zitadel.adminClientId": "test-admin-sa",
                "zitadel.adminSecretName": "test-admin-secret",
            },
        )
        jobs = find_all_manifests(manifests, kind="Job")
        # Filter to Canon's setup job (post-install), not Zitadel's own setup job (pre-install)
        canon_setup_jobs = [
            j
            for j in jobs
            if j.get("metadata", {}).get("name", "").endswith("-zitadel-setup")
            and "post-install"
            in j.get("metadata", {}).get("annotations", {}).get("helm.sh/hook", "")
        ]
        assert len(canon_setup_jobs) == 1, (
            f"Expected exactly one Canon zitadel-setup Job, got {len(canon_setup_jobs)}"
        )


# ---------------------------------------------------------------------------
# TestStripeSecret
# ---------------------------------------------------------------------------


class TestStripeSecret:
    """Stripe secret rendering for billing infrastructure."""

    def test_stripe_secret_created_with_values(self):
        """When secretKey is set, a Stripe Secret is created with all 8 env vars."""
        manifests = helm_template(
            set_values={
                "secrets.stripe.secretKey": "sk_test_123",
                "secrets.stripe.publishableKey": "pk_test_123",
                "secrets.stripe.webhookSecret": "whsec_test",
                "secrets.stripe.starterMonthlyPriceId": "price_sm",
                "secrets.stripe.starterAnnualPriceId": "price_sa",
                "secrets.stripe.proMonthlyPriceId": "price_pm",
                "secrets.stripe.proAnnualPriceId": "price_pa",
                "secrets.stripe.byokEncryptionKey": "enc_key",
            },
        )
        secrets = find_all_manifests(manifests, kind="Secret")
        stripe_secrets = [s for s in secrets if "stripe" in s.get("metadata", {}).get("name", "")]
        assert len(stripe_secrets) == 1, "Expected exactly one Stripe Secret"
        string_data = stripe_secrets[0].get("stringData", {})
        assert string_data.get("STRIPE_SECRET_KEY") == "sk_test_123"
        assert string_data.get("STRIPE_PUBLISHABLE_KEY") == "pk_test_123"
        assert string_data.get("STRIPE_WEBHOOK_SECRET") == "whsec_test"
        assert string_data.get("STRIPE_STARTER_MONTHLY_PRICE_ID") == "price_sm"
        assert string_data.get("STRIPE_STARTER_ANNUAL_PRICE_ID") == "price_sa"
        assert string_data.get("STRIPE_PRO_MONTHLY_PRICE_ID") == "price_pm"
        assert string_data.get("STRIPE_PRO_ANNUAL_PRICE_ID") == "price_pa"
        assert string_data.get("BYOK_ENCRYPTION_KEY") == "enc_key"

    def test_stripe_secret_skipped_with_existing_secret(self):
        """When existingSecret is set, no Stripe Secret is rendered."""
        manifests = helm_template(
            set_values={
                "secrets.stripe.existingSecret": "my-stripe",
            },
        )
        secrets = find_all_manifests(manifests, kind="Secret")
        stripe_secrets = [s for s in secrets if "stripe" in s.get("metadata", {}).get("name", "")]
        assert len(stripe_secrets) == 0, (
            "Stripe Secret should not be created when existingSecret is set"
        )

    def test_stripe_secret_skipped_without_values(self):
        """With defaults, no Stripe Secret is rendered."""
        manifests = helm_template()
        secrets = find_all_manifests(manifests, kind="Secret")
        stripe_secrets = [s for s in secrets if "stripe" in s.get("metadata", {}).get("name", "")]
        assert len(stripe_secrets) == 0, "Stripe Secret should not be created with default values"

    def test_deployment_mounts_stripe_secret(self):
        """Deployment envFrom should reference the Stripe secret when configured."""
        manifests = helm_template(
            set_values={
                "secrets.stripe.secretKey": "sk_test_123",
            },
        )
        dep = find_manifest(manifests, kind="Deployment")
        assert dep is not None
        names = _env_from_names(dep)
        stripe_refs = [n for n in names if "stripe" in n]
        assert len(stripe_refs) >= 1, f"Expected Stripe secret ref in envFrom, got {names}"


# ---------------------------------------------------------------------------
# TestSMTPSecret
# ---------------------------------------------------------------------------


class TestSMTPSecret:
    """SMTP secret rendering for email infrastructure."""

    def test_smtp_secret_created_with_values(self):
        """When host is set, an SMTP Secret is created with all 5 env vars."""
        manifests = helm_template(
            set_values={
                "secrets.smtp.host": "smtp.example.com",
                "secrets.smtp.port": "587",
                "secrets.smtp.user": "user@example.com",
                "secrets.smtp.password": "pass123",
                "secrets.smtp.from": "noreply@example.com",
            },
        )
        secrets = find_all_manifests(manifests, kind="Secret")
        smtp_secrets = [s for s in secrets if "smtp" in s.get("metadata", {}).get("name", "")]
        assert len(smtp_secrets) == 1, "Expected exactly one SMTP Secret"
        string_data = smtp_secrets[0].get("stringData", {})
        assert string_data.get("SMTP_HOST") == "smtp.example.com"
        assert string_data.get("SMTP_PORT") == "587"
        assert string_data.get("SMTP_USER") == "user@example.com"
        assert string_data.get("SMTP_PASSWORD") == "pass123"
        assert string_data.get("SMTP_FROM") == "noreply@example.com"

    def test_smtp_secret_skipped_with_existing_secret(self):
        """When existingSecret is set, no SMTP Secret is rendered."""
        manifests = helm_template(
            set_values={
                "secrets.smtp.existingSecret": "my-smtp",
            },
        )
        secrets = find_all_manifests(manifests, kind="Secret")
        smtp_secrets = [s for s in secrets if "smtp" in s.get("metadata", {}).get("name", "")]
        assert len(smtp_secrets) == 0, (
            "SMTP Secret should not be created when existingSecret is set"
        )

    def test_smtp_secret_skipped_without_values(self):
        """With defaults, no SMTP Secret is rendered."""
        manifests = helm_template()
        secrets = find_all_manifests(manifests, kind="Secret")
        smtp_secrets = [s for s in secrets if "smtp" in s.get("metadata", {}).get("name", "")]
        assert len(smtp_secrets) == 0, "SMTP Secret should not be created with default values"

    def test_deployment_mounts_smtp_secret(self):
        """Deployment envFrom should reference the SMTP secret when configured."""
        manifests = helm_template(
            set_values={
                "secrets.smtp.host": "smtp.example.com",
            },
        )
        dep = find_manifest(manifests, kind="Deployment")
        assert dep is not None
        names = _env_from_names(dep)
        smtp_refs = [n for n in names if "smtp" in n]
        assert len(smtp_refs) >= 1, f"Expected SMTP secret ref in envFrom, got {names}"


# ---------------------------------------------------------------------------
# TestAuth0M2M
# ---------------------------------------------------------------------------


class TestAuth0M2M:
    """Auth0 M2M credential rendering."""

    def test_auth0_secret_includes_m2m_fields(self):
        """When m2mClientId and m2mClientSecret are set, they appear in the Auth0 Secret."""
        manifests = helm_template(
            set_values={
                "secrets.auth0.domain": "test.auth0.com",
                "secrets.auth0.clientId": "cid",
                "secrets.auth0.clientSecret": "csec",
                "secrets.auth0.m2mClientId": "m2m-cid",
                "secrets.auth0.m2mClientSecret": "m2m-csec",
            },
        )
        secrets = find_all_manifests(manifests, kind="Secret")
        auth0_secrets = [s for s in secrets if "auth0" in s.get("metadata", {}).get("name", "")]
        assert len(auth0_secrets) == 1, "Expected exactly one Auth0 Secret"
        string_data = auth0_secrets[0].get("stringData", {})
        assert string_data.get("AUTH0_M2M_CLIENT_ID") == "m2m-cid"
        assert string_data.get("AUTH0_M2M_CLIENT_SECRET") == "m2m-csec"

    def test_auth0_secret_without_m2m_fields(self):
        """Auth0 Secret should still work without M2M fields."""
        manifests = helm_template(
            set_values={
                "secrets.auth0.domain": "test.auth0.com",
                "secrets.auth0.clientId": "cid",
                "secrets.auth0.clientSecret": "csec",
            },
        )
        secrets = find_all_manifests(manifests, kind="Secret")
        auth0_secrets = [s for s in secrets if "auth0" in s.get("metadata", {}).get("name", "")]
        assert len(auth0_secrets) == 1
        string_data = auth0_secrets[0].get("stringData", {})
        assert "AUTH0_M2M_CLIENT_ID" not in string_data
        assert "AUTH0_M2M_CLIENT_SECRET" not in string_data


# ---------------------------------------------------------------------------
# TestProductionSecretRefs
# ---------------------------------------------------------------------------


class TestProductionSecretRefs:
    """Production values should reference existing Stripe and SMTP secrets."""

    @pytest.fixture(autouse=True)
    def manifests(self):
        self._manifests = helm_template("chart/canon/values-production.yaml")

    def test_stripe_existing_secret_referenced(self):
        """Deployment envFrom should include ``canon-stripe`` in production."""
        dep = find_manifest(self._manifests, kind="Deployment")
        assert dep is not None
        names = _env_from_names(dep)
        assert "canon-stripe" in names, f"Expected 'canon-stripe' in envFrom refs, got {names}"

    def test_smtp_existing_secret_referenced(self):
        """Deployment envFrom should include ``canon-smtp`` in production."""
        dep = find_manifest(self._manifests, kind="Deployment")
        assert dep is not None
        names = _env_from_names(dep)
        assert "canon-smtp" in names, f"Expected 'canon-smtp' in envFrom refs, got {names}"
