import sys
from .cli import cli

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Default to interactive menu if no arguments are provided
        from .cli import interactive_menu
        interactive_menu()
    else:
        cli()

