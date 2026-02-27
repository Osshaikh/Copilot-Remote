class Animal:
    def __init__(self, name, sound):
        self.name = name
        self.sound = sound

    def speak(self):
        return f"{self.name} says {self.sound}"

# Object operations
dog = Animal("Dog", "Woof")
cat = Animal("Cat", "Meow")

print(dog.speak())  # Dog says Woof
print(cat.speak())  # Cat says Meow

# Changing object attribute
dog.sound = "Bark"
print(dog.speak())  # Dog says Bark
