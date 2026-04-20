# Minimal agent implementation based on agent-builder skill
import sys

def main():
    # Simple loop: read input, process, output
    while True:
        try:
            user_input = input("User: ")
        except EOFError:
            break
        if user_input.lower() in {"exit", "quit"}:
            print("Agent: Goodbye!")
            break
        # Here we would invoke model reasoning; placeholder echo
        print(f"Agent: You said '{user_input}'. (Model reasoning would happen here.)")

if __name__ == "__main__":
    main()
