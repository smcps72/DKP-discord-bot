# Railway reverse proxy (PostHog)

## Before you start

- Use domains matching your PostHog region:
  - US: `us.i.posthog.com`
  - EU: `eu.i.posthog.com`
- Don't use obvious path names like `/analytics`, `/tracking`, `/telemetry`, or `/posthog`. Blockers will catch them. Use something unique to your app instead.

This guide shows you how to deploy a PostHog reverse proxy on [Railway](https://railway.app/) and configure **this bot** to send events through it.

## How it works

Railway provides a one-click deployment template that runs an nginx-based reverse proxy. When deployed, Railway gives you a domain that routes all requests to PostHog's servers.

Request flow:

1. User triggers an event in the bot
2. Request goes to your Railway domain (e.g., `your-project.up.railway.app`)
3. The nginx proxy running on Railway forwards the request to PostHog ingestion
4. PostHog processes the request and returns a response
5. The proxy returns PostHog's response

## Prerequisites

- Railway account (free tier works)
- A PostHog project API key

## Setup

## 1) Deploy the template

Deploy the preconfigured PostHog reverse proxy on Railway:

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/posthog-proxy?referralCode=FQRCYT)

## 2) Configure your region

During deployment, Railway prompts you to set the `POSTHOG_CLOUD_REGION` environment variable:

- Set to `us` for US region
- Set to `eu` for EU region

## 3) Get your Railway domain

Once deployed, Railway provides a domain like `your-project-name.up.railway.app`.

You can find it in Railway:

- Project
- Settings
- Networking

## 4) Configure the bot

This bot uses the Python `posthog` SDK and reads PostHog configuration from environment variables.

Set these in your `.env.local` (either at repo root or `secrets/.env.local`):

- `POSTHOG_API_KEY`:
  - Your PostHog project API key
- `POSTHOG_HOST`:
  - Your Railway domain URL, e.g. `https://your-project-name.up.railway.app`

Example:

```bash
POSTHOG_API_KEY=phc_...
POSTHOG_HOST=https://your-project-name.up.railway.app
POSTHOG_DEBUG=false
```

## 5) Add a custom domain (optional)

For better blocking resistance, use your own domain instead of Railway's default:

1. Go to your Railway project's Settings -> Networking
2. Click Add Domain
3. Follow Railway's custom domains guide: https://docs.railway.app/guides/public-networking#custom-domains

Then update the bot's `POSTHOG_HOST` to your custom domain:

```bash
POSTHOG_HOST=https://e.yourdomain.com
```

## Verify your setup

1. Test the proxy directly:

```bash
curl -I https://your-project-name.up.railway.app/decide?v=3
```

You should see a `200 OK`.

2. Run the bot with `POSTHOG_DEBUG=true` temporarily and trigger any slash command

3. Confirm events appear in PostHog

## Troubleshooting

## Proxy stops working periodically

- Check for sleep/idle settings (free tier services can sleep)
- Check Railway metrics for CPU/memory spikes
- Check Railway logs for connection errors

## 502 Bad Gateway

- Confirm `POSTHOG_CLOUD_REGION` matches your PostHog project region
- Confirm the Railway service is running
- Check Railway logs
