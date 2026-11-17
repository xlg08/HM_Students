"""Run HTTP service using the same local environment as the CLI."""
import sys

user_paths = [path for path in sys.path if 'AppData' in path and 'site-packages' in path]
sys.path[:] = [path for path in sys.path if path not in user_paths] + user_paths

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('backend.app:app', host='127.0.0.1', port=8010, workers=1)
