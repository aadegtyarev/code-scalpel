import json
import click
import os

def save_note(note):
    notes = []
    if os.path.exists('notes.json'):
        with open('notes.json', 'r') as file:
            notes = json.load(file)
    notes.append(note)
    with open('notes.json', 'w') as file:
        json.dump(notes, file)

@click.group()
def cli():
    pass

@cli.command()
@click.argument('note')
def add(note):
    save_note(note)
    click.echo(f'Note added: {note}')

@cli.command()
def list_notes():
    if not os.path.exists('notes.json'):
        click.echo('No notes found.')
        return
    with open('notes.json', 'r') as file:
        notes = json.load(file)
    for index, note in enumerate(notes, start=1):
        click.echo(f'{index}: {note}')