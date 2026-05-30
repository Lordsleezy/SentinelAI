# calculator.py

def add(x, y):
    return x + y
def subtract(x, y):
    return x - y
def multiply(x, y):
    return x * y
def divide(x, y):
    if y == 0:
        return "Error: Division by zero"
    return x / y

def main():
    print("Simple Calculator")
    while True:
        print("Options: add, subtract, multiply, divide, exit")
        choice = input("Enter your choice: ")
        if choice == 'exit':
            break
        num1 = float(input("Enter first number: "))
        num2 = float(input("Enter second number: "))
        if choice == 'add':
            print(f"Result: {add(num1, num2)}")
        elif choice == 'subtract':
            print(f"Result: {subtract(num1, num2)}")
        elif choice == 'multiply':
            print(f"Result: {multiply(num1, num2)}")
        elif choice == 'divide':
            print(f"Result: {divide(num1, num2)}")
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    main()