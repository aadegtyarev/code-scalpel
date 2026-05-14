import click

def main(args=None):
    @click.group()
    def cli():
        pass

    @cli.command()
    def add(note):
        print(f'Adding note: {note}')

    @cli.command()
    def list():
        print('Listing notes')

    @cli.command()
    def search(query):
        print(f'Searching for: {query}')

    @cli.command()
    def delete(index):
        print(f'Deleting note at index: {index}')

    cli.main(args=args, prog_name='notes-cli')