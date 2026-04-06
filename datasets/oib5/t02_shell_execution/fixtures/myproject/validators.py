import re

def validate_email(email):
    pattern = r'^[\w.-]+@[\w.-]+\.\w+$'
    return bool(re.match(pattern, email))

def validate_age(age):
    return isinstance(age, int) and 0 < age < 150
