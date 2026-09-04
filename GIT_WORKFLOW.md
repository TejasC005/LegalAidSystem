# Team Git Workflow & Pull Request (PR) Guide

This guide outlines the standard Git collaboration workflow for the **LEXIS** project. All team members must follow this **Pull Request (PR)** process to ensure code quality, maintain test coverage, and keep our main branches clean.

---

## 📌 Branch Roles & Permissions

1. **`main` (Production / Stable)**
   - Represents verified, production-ready code.
   - ⚠️ **DIRECT PUSHES TO `main` ARE STRICTLY PROHIBITED.**
   - Updated **only by the Team Maintainer** merging from `develop`.

2. **`develop` (Integration / Staging)**
   - The primary branch where approved feature PRs are merged.
   - ⚠️ **DIRECT PUSHES TO `develop` ARE FORBIDDEN FOR TEAM MEMBERS.**
   - All code enters `develop` strictly through **Pull Requests (PRs)** reviewed and accepted by the Maintainer.

3. **`feature/<feature-name>` or `fix/<bug-name>` (Working Branches)**
   - Created by team members for every single feature or bug fix off `develop`.
   - Examples: `feature/user-auth`, `fix/pdf-parser-bug`, `feature/lawyer-dashboard`.

---

## 🚀 Team Member Workflow: From Code to Pull Request

### Step 1: Start from the Latest `develop`
Always start your work from an up-to-date `develop` branch.

```bash
# 1. Switch to develop
git checkout develop

# 2. Pull the latest develop code
git pull origin develop

# 3. Create your feature branch
git checkout -b feature/your-feature-name
```

---

### Step 2: Develop and Commit Changes
Make your changes and commit them cleanly with clear commit messages.

```bash
# Stage modified and new files
git add .

# Commit with a descriptive message
git commit -m "feat(auth): implement email OTP verification"
```

---

### Step 3: Push your Branch & Open a Pull Request (PR)
Push your feature branch to the remote repository and open a Pull Request.

```bash
# Push feature branch to GitHub
git push -u origin feature/your-feature-name
```

**Opening the Pull Request on GitHub:**
1. Navigate to the repository on GitHub.
2. Click **Compare & pull request** next to your recently pushed branch.
3. Ensure the **base branch is set to `develop`** (`base: develop` ⬅️ `compare: feature/your-feature-name`).
4. Fill out the PR template/description explaining what changes were made.
5. Click **Create Pull Request** and tag the **Maintainer** for review.

---

## 🔄 Handling Conflicts (When another PR was merged before yours)

If another team member's PR is merged into `develop` before yours, GitHub will indicate that your PR has merge conflicts or cannot be automatically merged.

To update your PR branch with the latest `develop` changes:

```bash
# 1. Fetch latest changes from remote
git fetch origin

# 2. Rebase your feature branch on top of origin/develop
git rebase origin/develop

# 3. If there are conflicts, resolve them in your code editor, then stage them:
git add <path-to-resolved-file>

# 4. Continue the rebase:
git rebase --continue

# 5. Safely update your remote feature branch (this automatically updates your PR on GitHub)
git push --force-with-lease origin feature/your-feature-name
```

---

## 🛡️ Maintainer Review Process (Accepting or Rejecting PRs)

*(For Project Maintainer / Lead)*

As the Maintainer, you are responsible for reviewing all incoming Pull Requests to `develop`:

1. **Review Code**: Inspect code changes, architecture compliance, security, and unit tests on GitHub.
2. **Decision**:
   - ✅ **Accept & Merge**: Click **Squash and Merge** (or **Merge Pull Request**) into `develop`.
   - 💬 **Request Changes**: Leave comments on specific lines requesting improvements from the developer before merging.
   - ❌ **Reject / Close**: If the PR is unnecessary or violates project guidelines, close the PR with an explanation.

---

## 🚀 Maintainer Workflow: Updating `main` from `develop`

When `develop` accumulates stable, verified features and is ready for release:

```bash
# 1. Switch to main
git checkout main

# 2. Ensure main is up to date
git pull origin main

# 3. Merge develop into main
git merge develop -m "release: milestone update"

# 4. Push updated main to remote repository
git push origin main

# 5. Return to develop branch for ongoing work
git checkout develop
```

---

## 📋 Summary of Rules for Team Members
- ✅ **Work in feature branches** (`feature/your-feature-name`).
- ✅ **Target `develop`** when creating a Pull Request.
- ✅ **Rebase on `develop`** if conflicts arise before PR approval.
- ❌ **Do NOT push directly to `develop` or `main`**.
- ❌ **Do NOT merge your own PRs** without Maintainer review.
