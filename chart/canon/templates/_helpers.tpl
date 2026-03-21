{{/*
Expand the name of the chart.
*/}}
{{- define "canon.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "canon.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "canon.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "canon.labels" -}}
helm.sh/chart: {{ include "canon.chart" . }}
{{ include "canon.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "canon.selectorLabels" -}}
app.kubernetes.io/name: {{ include "canon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Service account name
*/}}
{{- define "canon.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "canon.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Container image
*/}}
{{- define "canon.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag -}}
{{- if .Values.image.registry -}}
{{ .Values.image.registry }}/{{ .Values.image.repository }}:{{ $tag }}
{{- else -}}
{{ .Values.image.repository }}:{{ $tag }}
{{- end -}}
{{- end }}

{{/*
Secret name for GitHub App credentials
*/}}
{{- define "canon.githubSecretName" -}}
{{- if .Values.secrets.githubApp.existingSecret -}}
{{ .Values.secrets.githubApp.existingSecret }}
{{- else -}}
{{ include "canon.fullname" . }}-github
{{- end -}}
{{- end }}

{{/*
Secret name for Anthropic credentials
*/}}
{{- define "canon.anthropicSecretName" -}}
{{- if .Values.secrets.anthropic.existingSecret -}}
{{ .Values.secrets.anthropic.existingSecret }}
{{- else -}}
{{ include "canon.fullname" . }}-anthropic
{{- end -}}
{{- end }}

{{/*
Secret name for Neon DB credentials
*/}}
{{- define "canon.neonSecretName" -}}
{{- if .Values.secrets.neon.existingSecret -}}
{{ .Values.secrets.neon.existingSecret }}
{{- else -}}
{{ include "canon.fullname" . }}-neon
{{- end -}}
{{- end }}

{{/*
Secret name for GCP credentials
*/}}
{{- define "canon.gcpSecretName" -}}
{{- if .Values.secrets.gcp.existingSecret -}}
{{ .Values.secrets.gcp.existingSecret }}
{{- else -}}
{{ include "canon.fullname" . }}-gcp
{{- end -}}
{{- end }}

{{/*
Secret name for Auth0 credentials
*/}}
{{- define "canon.auth0SecretName" -}}
{{- if .Values.secrets.auth0.existingSecret -}}
{{ .Values.secrets.auth0.existingSecret }}
{{- else -}}
{{ include "canon.fullname" . }}-auth0
{{- end -}}
{{- end }}

{{/*
Secret name for OIDC credentials
*/}}
{{- define "canon.oidcSecretName" -}}
{{- if .Values.secrets.oidc.existingSecret -}}
{{ .Values.secrets.oidc.existingSecret }}
{{- else -}}
{{ include "canon.fullname" . }}-oidc
{{- end -}}
{{- end }}

{{/*
Secret name for MCP API key
*/}}
{{- define "canon.mcpSecretName" -}}
{{- if .Values.secrets.mcp.existingSecret -}}
{{ .Values.secrets.mcp.existingSecret }}
{{- else -}}
{{ include "canon.fullname" . }}-mcp
{{- end -}}
{{- end }}

{{/*
Secret name for Jira credentials
*/}}
{{- define "canon.jiraSecretName" -}}
{{- if .Values.secrets.jira.existingSecret -}}
{{ .Values.secrets.jira.existingSecret }}
{{- else -}}
{{ include "canon.fullname" . }}-jira
{{- end -}}
{{- end }}

{{/*
Secret name for PostHog credentials
*/}}
{{- define "canon.posthogSecretName" -}}
{{- if .Values.secrets.posthog.existingSecret -}}
{{ .Values.secrets.posthog.existingSecret }}
{{- else -}}
{{ include "canon.fullname" . }}-posthog
{{- end -}}
{{- end }}

{{/*
Secret name for Slack credentials
*/}}
{{- define "canon.slackSecretName" -}}
{{- if .Values.secrets.slack.existingSecret -}}
{{ .Values.secrets.slack.existingSecret }}
{{- else -}}
{{ include "canon.fullname" . }}-slack
{{- end -}}
{{- end }}
