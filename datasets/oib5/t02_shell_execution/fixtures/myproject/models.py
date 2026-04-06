class User:
    def __init__(self, name, age):
        self.name = name
        self.age = age

    def greet(self):
        return f'Hi, {self.name}'

class Product:
    def __init__(self, title, price):
        self.title = title
        self.price = price

    def display(self):
        return f'{self.title}: ${self.price}'
