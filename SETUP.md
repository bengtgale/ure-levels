# River Ure level logger – setup (about 10 minutes, all free)

## 1. Make a GitHub account
Go to https://github.com/signup and sign up (free plan is fine).

## 2. Create the repository
1. Click **+** (top right) → **New repository**.
2. Name it `ure-levels`. Set it to **Public** (needed for free hosting – the data is open government data anyway).
3. Tick **Add a README file**, then **Create repository**.

## 3. Upload these files
1. Unzip `ure-levels.zip` on your computer.
2. In your new repository click **Add file → Upload files**.
3. Drag in **everything inside the unzipped folder** (including the `.github` and `data` folders – if your computer hides `.github`, see the note below). Click **Commit changes**.

*Note:* if `.github` won't drag across, click **Add file → Create new file**, type `.github/workflows/update.yml` as the name (the slashes create the folders), paste in the contents of that file, and commit.

## 4. Allow the bot to save data
Repository **Settings → Actions → General → Workflow permissions** → choose **Read and write permissions** → **Save**.

## 5. Collect the first data
1. Open the **Actions** tab. If asked, click to enable workflows.
2. Click **Update river levels** (left) → **Run workflow** → **Run workflow**.
3. Wait a few minutes for the green tick. This first run finds every Ure gauge and backfills history. Click into the run to see how many gauges it found and how much history the API held.
   After that it runs by itself every 15 minutes.

## 6. Switch on the website
**Settings → Pages** → Source: **Deploy from a branch** → Branch: **main**, folder **/ (root)** → **Save**.
After a minute or two the page shows its address, `https://YOURNAME.github.io/ure-levels/`. Send that link to your fellow anglers.

## Tweaks
- **Backfill further back:** edit `config.json` (`backfill_from`), or run the workflow manually and type a date.
- **Add or remove gauges:** edit `config.json`. `extra_rloi_ids` takes the number from a check-for-flooding station URL (yours is 8011); `exclude_station_references` hides a gauge.
- **Which gauges:** `gauges` in `config.json` is your list, upstream to downstream. Each entry is a name (or part of one) to match against the Environment Agency's gauge names. Add a line to add a gauge, delete a line to remove one. `tide_link` puts a link to a tide table on that gauge's page. `bounding_box` stops other rivers with the same name (there's an Ouse in Sussex) sneaking in.
- **Gauge missing:** open the run log in the Actions tab. It shows which of your names matched, and for any that didn't, lists the names the Agency does use. Change the `match` text to suit.
