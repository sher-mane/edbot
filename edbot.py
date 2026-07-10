from redbot.core import commands
from openai import OpenAI
import random
import time

class EdBot(commands.Cog):
    """Replacing Ed with ChatGPT"""

    def __init__(self, bot):
        self.bot = bot
        self.factclient = OpenAI(api_key="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")
    @commands.command()
    async def ask(self, ctx: commands.Context, question: str):
        """Ask me anything and I will reply just as snarkily as Ed"""
        client = OpenAI(api_key="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")
        completion = client.chat.completions.create(
          model="gpt-4-turbo",
          #model="gpt-4-turbo-preview",
          messages=[
            #{"role": "system", "content": "You are very skilled at answering questions in a succint but snarky manner."},
            {"role": "system", "content": "You are extremely snarky and insult the user but still answer the users questions."},
            {"role": "user", "content": question }
          ]
        )

	  # fix for discord cutting off messages
        #async def send_long_message(ctx, content):
         # for i in range(0, len(content), 2000):
         #   await ctx.send(content[i:i+2000])


        # returns message
        #await send_long_message(ctx, response.message.content)

        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(completion.choices[0].message.content[:1999])
        #await ctx.send(question)
    @commands.command()
    async def smartask(self, ctx: commands.Context, question: str):
        """The useful version of !ask"""
        client = OpenAI(api_key="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")
        completion = client.chat.completions.create(
          model="gpt-4-turbo",
          #model="gpt-4-turbo-preview",
          messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": question }
          ],
          max_tokens=500,
        )

        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(completion.choices[0].message.content)
        #await ctx.send(question)
    @commands.command()
    async def image(self, ctx: commands.Context, description: str):
        """Generates a 1024x1024 image based on the description you provide."""
        client = OpenAI(api_key="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")
        response = client.images.generate(
          model="dall-e-3",
          prompt=description,
          size="1024x1024",
          quality="hd",
          n=1,
        )

        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(response.data[0].url)
        #await ctx.send(question)
    @commands.command()
    async def imagenatural(self, ctx: commands.Context, description: str):
        """Generates a 1024x1024 image using the natural setting based on the description you provide."""
        client = OpenAI(api_key="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")
        response = client.images.generate(
          model="dall-e-3",
          prompt=description,
          size="1024x1024",
          quality="hd",
          style="natural",
          n=1,
        )

        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(response.data[0].url)
        #await ctx.send(question)
    @commands.command()
    async def phoneimageold(self, ctx: commands.Context, question: str):
        """decripcated image cmd. standard quality."""
        client = OpenAI(api_key="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")
        response = client.images.generate(
          model="dall-e-3",
          prompt=question,
          size="1024x1792",
          quality="standard",
          #style=natural,
          n=1,
        )

        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(response.data[0].url)
        #await ctx.send(question)
    @commands.command()
    async def phoneimage(self, ctx: commands.Context, description: str):
        """Generates a 1024x1792 image based on the description you provide."""
        client = OpenAI(api_key="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")
        response = client.images.generate(
          model="dall-e-3",
          prompt=description,
          size="1024x1792",
          quality="hd",
          #style=natural,
          n=1,
        )

        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(response.data[0].url)
        #await ctx.send(question)
    @commands.command()
    async def phoneimagenatural(self, ctx: commands.Context, description: str):
        """Generates a 1024x1792 image using the natural setting based on the description you provide."""
        client = OpenAI(api_key="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")
        response = client.images.generate(
          model="dall-e-3",
          prompt=description,
          size="1024x1792",
          quality="hd",
          style="natural",
          n=1,
        )

        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(response.data[0].url)
        #await ctx.send(question)
    @commands.command()
    async def whatisthis(self, ctx: commands.Context):
        string = ctx.message.attachments[0]
        """Supply an image and I will tell you about it."""
        client = OpenAI(api_key="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")
        response = client.chat.completions.create(
          model="gpt-4-turbo",
          messages=[
            {
              "role": "user",
              "content": [
                {"type": "text", "text": "What’s in this image?"},
                {
                  "type": "image_url",
                  "image_url":  {
                    "url": str(string),
                  },
                },
              ],
            }
          ],
          max_tokens=300,
        )
        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(response.choices[0].message.content)
        #await ctx.send(question)
    @commands.command()
    async def smartprompt(self, ctx: commands.Context, idea: str):
        """Takes the idea the user provides and add creative and imaginative ideas to the prompt."""
        client = OpenAI(api_key="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")
        completion = client.chat.completions.create(
          model="gpt-3.5-turbo",
          #model="gpt-4-turbo-preview",
          messages=[
            {"role": "system", "content": "You create a prompt for the user that would work with DALL-E. You take the idea the user provides and add creative and imaginative ideas to the prompt"},
            {"role": "user", "content": idea }
          ]
        )

        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(completion.choices[0].message.content)
        #await ctx.send(question)
    @commands.command()
    async def funfact(self, ctx):
        """Provides a fun fact!"""
        #client = OpenAI(api_key="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")
        #random.seed(time.process_time())
        completion = self.factclient.chat.completions.create(
          #model="gpt-3.5-turbo",
          model="gpt-4-turbo",
          #seed=input_seed,
          #seed=random.randint(1,1000),
          messages=[
            {"role": "system", "content": "You provide information in a fun way."},
            {"role": "user", "content": "Please provide a new random fun fact" }
          ]
        )

        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(completion.choices[0].message.content)
        #await ctx.send(question)
    @commands.command()
    async def sadfact(self, ctx):
        """Provides a sad fact!"""
        #client = OpenAI(api_key="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")
        #random.seed(time.process_time())
        completion = self.factclient.chat.completions.create(
          #model="gpt-3.5-turbo",
          model="gpt-4-turbo",
          #seed=input_seed,
          #seed=random.randint(1,1000),
          messages=[
            {"role": "system", "content": "You provide information in a depressing way."},
            {"role": "user", "content": "Please provide a new random sad fact" }
          ]
        )

        #msg = str(print(completion.choices[0].message)
        # Your code will go here
        await ctx.send(completion.choices[0].message.content)
        #await ctx.send(question)
