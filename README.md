# Weihan's AI Tools — College Toolkit

A single-page college toolkit: dashboard, expenses, to-do, class schedule, GPA,
assignments (with Canvas LMS sync), study timer, habits, wellness check-ins,
contacts, survival guide, and Madison WI weather. Installable as a PWA, works
fully offline, and optionally syncs to your own free Supabase project.

**Live site:** https://linweihan7.github.io/college-toolkit/

## Cloud sync setup (one time, ~5 minutes)

1. Create a free account at [supabase.com](https://supabase.com) (easiest: "Continue with GitHub").
2. **New project** → name it anything → pick a US Central/East region → Create.
3. In the project: **SQL Editor → New query**, paste and run:

   ```sql
   create table public.toolkit_data (
     user_id uuid not null references auth.users(id) on delete cascade,
     key text not null,
     value jsonb,
     updated_at timestamptz not null default now(),
     primary key (user_id, key)
   );

   alter table public.toolkit_data enable row level security;

   create policy "Users manage only their own rows"
     on public.toolkit_data
     for all
     using (auth.uid() = user_id)
     with check (auth.uid() = user_id);
   ```

   The `row level security` part is what makes the public "anon key" safe:
   the database itself refuses to show anyone rows that aren't theirs.

4. **Authentication → URL Configuration**:
   - Site URL: `https://linweihan7.github.io/college-toolkit/`
   - Add redirect URLs: `https://linweihan7.github.io/college-toolkit/index.html`
     (and `http://localhost:8934/index.html` if you develop locally)
5. **Settings → API**: copy the **Project URL** and the **anon public** key.
6. Open the app → Dashboard → **Account & Cloud Sync** → paste both → Save
   Connection → enter your email → tap the magic link it sends you.

Data model: every feature stores one JSON blob per key in `localStorage`
(offline-first); sync mirrors those keys to the `toolkit_data` table with
last-write-wins per key, pushed automatically ~2s after each change and pulled
at startup / sign-in / Sync Now.

## Development

Plain static site — open `index.html` or serve the folder:

```bash
python3 -m http.server 8934
```
