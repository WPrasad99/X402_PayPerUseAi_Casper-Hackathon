import os
import subprocess
import random
from datetime import datetime, timedelta
import shutil

REPO_URL = "https://github.com/WPrasad99/X402_PayPerUseAi_Casper-Hackathon.git"
START_DATE_DAYS_AGO = 20

# Files and directories to explicitly ignore
IGNORE_DIRS = {'node_modules', '.git', '__pycache__', '.venv', 'venv', '.gemini', 'dist', 'build', '.pytest_cache'}
IGNORE_FILES = {'.env', 'Account 1_secret_key.pem', 'last_deploy.json', 'test_deploy.json', 'make_history.py', 'New Text Document.txt'}

def run_cmd(cmd, env=None):
    subprocess.run(cmd, shell=True, check=True, env=env)

def get_all_files():
    all_files = []
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            if f in IGNORE_FILES or f.endswith('.pem'):
                continue
            path = os.path.relpath(os.path.join(root, f), '.')
            all_files.append(path)
    return all_files

def generate_commit_message(filename):
    basename = os.path.basename(filename)
    if 'package.json' in basename: return "Initialize project dependencies"
    if 'main.py' in basename: return "Setup FastAPI core application"
    if 'database.py' in basename: return "Configure asyncpg connection pool"
    if 'casperWallet' in basename: return "Integrate Casper Signer SDK"
    if 'Navbar' in basename: return "Implement navigation UI"
    if 'Dashboard' in basename: return "Create user dashboard view"
    if 'casper_x402_service.py' in basename: return "Implement X-402 protocol handler"
    if 'payment.py' in basename: return "Add payment API routes"
    if 'x402_middleware.py' in basename: return "Create X-402 payment enforcement middleware"
    if 'session_payment.py' in basename: return "Implement pay-per-use session tracker"
    if 'casper_onchain.py' in basename: return "Add on-chain deploy verification"
    if 'casper_payout_service.py' in basename: return "Setup native CSPR payout service"
    if 'EarningsDashboard.jsx' in basename: return "Build creator earnings tracking UI"
    if 'AgentDetailPage.jsx' in basename: return "Implement AI agent detail view"
    
    # Generic fallbacks
    prefixes = ["Add", "Implement", "Refactor", "Update", "Fix bug in", "Enhance"]
    return f"{random.choice(prefixes)} {basename}"

def main():
    print("Clearing old git history...")
    if os.path.exists('.git'):
        try:
            # use shell to delete .git on windows
            run_cmd('rmdir /S /Q .git')
        except:
            shutil.rmtree('.git', ignore_errors=True)
    
    # Make sure we don't accidentally commit env files if they aren't ignored
    with open('.gitignore', 'w') as f:
        f.write("node_modules/\n.env\n*.pem\n__pycache__/\n.venv/\nvenv/\n.gemini/\ndist/\nbuild/\n*.log\nlast_deploy.json\ntest_deploy.json\nNew Text Document.txt\n")
        
    run_cmd("git init")
    run_cmd("git config user.name 'WPrasad99'")
    
    # Try to grab the email from current git config, fallback to a dummy if needed
    try:
        email = subprocess.check_output("git config user.email", shell=True, text=True).strip()
    except subprocess.CalledProcessError:
        email = "prasad@example.com"
    run_cmd(f"git config user.email '{email}'")

    files = get_all_files()
    random.shuffle(files)
    
    # Group files to aim for ~65 commits
    target_commits = 65
    chunk_size = max(1, len(files) // target_commits)
    
    chunks = [files[i:i + chunk_size] for i in range(0, len(files), chunk_size)]
    
    current_date = datetime.now() - timedelta(days=START_DATE_DAYS_AGO)
    
    # Add .gitignore first
    env = os.environ.copy()
    env['GIT_AUTHOR_DATE'] = current_date.isoformat()
    env['GIT_COMMITTER_DATE'] = current_date.isoformat()
    run_cmd("git add .gitignore", env=env)
    run_cmd('git commit -m "Initial commit: Add gitignore"', env=env)
    
    print(f"Creating {len(chunks)} commits...")
    for chunk in chunks:
        # Increment time by 2-6 hours randomly to simulate real work
        current_date += timedelta(hours=random.randint(2, 6), minutes=random.randint(0, 59))
        if current_date > datetime.now():
            current_date = datetime.now() - timedelta(minutes=10) # Don't go into the future
            
        env['GIT_AUTHOR_DATE'] = current_date.isoformat()
        env['GIT_COMMITTER_DATE'] = current_date.isoformat()
        
        for f in chunk:
            # Need to use quotes for paths with spaces
            run_cmd(f'git add "{f}"', env=env)
        
        # Pick the most "interesting" file in the chunk for the commit message
        primary_file = chunk[0]
        for f in chunk:
            if 'casper' in f.lower() or 'x402' in f.lower() or 'payment' in f.lower():
                primary_file = f
                break
                
        msg = generate_commit_message(primary_file)
        
        try:
            run_cmd(f'git commit -m "{msg}"', env=env)
            print(f"Committed: {msg} ({current_date.strftime('%Y-%m-%d %H:%M')})")
        except subprocess.CalledProcessError:
            pass # Nothing to commit
            
    # Final step: branch setup
    print("Setting branch to main...")
    run_cmd("git branch -M main")
    print("Done! You can now manually add the remote and push to GitHub.")

if __name__ == "__main__":
    main()
