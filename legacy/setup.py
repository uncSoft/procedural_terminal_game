
import sys
import subprocess
import venv
import os

# --- Configuration ---
VENV_DIR = "venv"
REQUIREMENTS = {
    "all": ["requests"],
    "win32": ["windows-curses"]
}

def create_requirements_file():
    """Creates the requirements.txt file based on the operating system."""
    print("--- Creating requirements.txt ---")
    
    # Base requirements for all systems
    packages = REQUIREMENTS["all"]

    # Add OS-specific requirements
    if sys.platform in REQUIREMENTS:
        packages.extend(REQUIREMENTS[sys.platform])

    with open("requirements.txt", "w") as f:
        for package in packages:
            f.write(f"{package}\n")
    
    print("Successfully created requirements.txt:")
    with open("requirements.txt", "r") as f:
        print(f.read())

def create_virtual_environment():
    """Creates a virtual environment if it doesn't exist."""
    if not os.path.exists(VENV_DIR):
        print(f"--- Creating virtual environment in '{VENV_DIR}' ---")
        try:
            venv.create(VENV_DIR, with_pip=True)
            print("Virtual environment created successfully.")
        except Exception as e:
            print(f"Error creating virtual environment: {e}")
            sys.exit(1)
    else:
        print(f"--- Virtual environment '{VENV_DIR}' already exists ---")

def get_pip_path():
    """Gets the path to the pip executable in the virtual environment."""
    if sys.platform == "win32":
        return os.path.join(VENV_DIR, "Scripts", "pip.exe")
    else:
        return os.path.join(VENV_DIR, "bin", "pip")

def install_dependencies():
    """Installs dependencies from requirements.txt into the virtual environment."""
    print("\n--- Installing dependencies ---")
    pip_path = get_pip_path()
    
    if not os.path.exists(pip_path):
        print(f"Error: pip executable not found at {pip_path}")
        sys.exit(1)

    try:
        subprocess.check_call([pip_path, "install", "-r", "requirements.txt"])
        print("Dependencies installed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error installing dependencies: {e}")
        sys.exit(1)

def print_instructions():
    """Prints instructions on how to run the game."""
    print("\n--- Setup Complete! ---")
    print("\nTo run the game, follow these steps:")
    
    if sys.platform == "win32":
        print(f"1. Activate the virtual environment:")
        print(f"   .\\{VENV_DIR}\\Scripts\\activate")
        print(f"\n2. Run the game:")
        print(f"   python main.py")
    else:
        print(f"1. Activate the virtual environment:")
        print(f"   source {VENV_DIR}/bin/activate")
        print(f"\n2. Run the game:")
        print(f"   python3 main.py")
        
    print("\n(When you are finished, you can leave the virtual environment by typing 'deactivate')")


if __name__ == "__main__":
    print("Starting environment setup for the Procedural Terminal Game...")
    
    # Check for Python 3
    if sys.version_info < (3, 6):
        print("Error: This game requires Python 3.6 or newer.")
        sys.exit(1)
        
    create_requirements_file()
    create_virtual_environment()
    install_dependencies()
    print_instructions()
