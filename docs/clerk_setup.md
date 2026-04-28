# Clerk Setup — Account Creation Walkthrough

This guide creates the free Clerk application that guards the Next.js frontend.
It takes about 10 minutes.

---

## 1. Create a Clerk Account

1. Open **https://clerk.com** and click **Start for free**.
2. Sign up with GitHub (easiest — it reuses your existing session).
3. Clerk creates a personal workspace automatically. No credit card required.

---

## 2. Create the Application

1. In the Clerk Dashboard, click **Create application**.
2. **Application name:** `Anime RAG`
3. **Sign-in options:** tick **Email address** and **Google** (Google requires no extra config at this stage).
4. Click **Create application**.

Clerk opens the **Quickstart** page. You can ignore the framework-specific snippet — we set everything up manually below.

---

## 3. Copy the API Keys

On the Quickstart page (or via **API Keys** in the left sidebar):

| Clerk key | Where it goes |
|---|---|
| **Publishable key** (`pk_test_…`) | `apps/web/.env.local` → `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` |
| **Secret key** (`sk_test_…`) | `apps/web/.env.local` → `CLERK_SECRET_KEY` |
| **Secret key** (same value) | `apps/api/.env` → `CLERK_SECRET_KEY` (JWT verification on FastAPI side) |

Create `apps/web/.env.local` (already git-ignored):

```bash
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_REPLACE_ME
CLERK_SECRET_KEY=sk_test_REPLACE_ME

# API base URL — change for production
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 4. Configure Redirect URLs

In the Clerk Dashboard → **Paths** (left sidebar):

| Setting | Value |
|---|---|
| Sign-in URL | `/sign-in` |
| Sign-up URL | `/sign-up` |
| After sign-in URL | `/chat` |
| After sign-up URL | `/chat` |

Leave everything else at the default.

---

## 5. (Optional) Google OAuth

If you enabled Google sign-in in step 2:

1. Go to **User & Authentication → Social connections → Google**.
2. Clerk provides a shared OAuth app for development — click **Use Clerk's credentials**. No Google Cloud setup needed during development.
3. For production you'll replace this with your own Google OAuth client.

---

## 6. Enable JWT Templates (for FastAPI)

The FastAPI backend verifies the Clerk JWT on the `/api/v1/recommend` route.

1. Dashboard → **JWT Templates** → **New template**.
2. Choose **Blank**.
3. **Name:** `anime-rag-api`
4. Leave claims at default (no custom claims needed).
5. Click **Save**.

The FastAPI middleware validates tokens using Clerk's JWKS endpoint:

```
https://api.clerk.com/v1/jwks
```

This URL is already set in `apps/api/.env` as `CLERK_JWKS_URL`.

---

## 7. Verify the Setup

```bash
# Start the stack
make up

# In a separate terminal, open the frontend
cd apps/web && pnpm dev
```

Navigate to `http://localhost:3000`. You should be redirected to the Clerk-hosted sign-in page. After signing in you land on `/chat`.

---

## 8. Production Checklist

Before deploying to production, revisit the Clerk Dashboard:

- [ ] Switch from **Development** instance to **Production** instance (Clerk Dashboard → top-left instance toggle).
- [ ] Replace shared Google OAuth credentials with your own Google Cloud client.
- [ ] Set the production domain in **Paths → Allowed origins**.
- [ ] Rotate the secret key — never commit it.
- [ ] Enable **Bot protection** (Dashboard → **Attack protection**).
