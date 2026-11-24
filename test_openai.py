from openai import OpenAI

client = OpenAI()

client.models.list()

print("OpenAI API connection successful.")