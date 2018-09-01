import os
import requests
from flask import Flask, session, request, render_template, flash, redirect, url_for, abort, jsonify
from flask_session import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from wtforms import Form, BooleanField, StringField, PasswordField, validators, SelectField
from passlib.hash import sha256_crypt

app = Flask(__name__)

# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Configure session to use filesystem
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set up database
engine = create_engine(os.getenv("DATABASE_URL"))
db = scoped_session(sessionmaker(bind=engine))

class SearchForm(Form):
    choices = [('ISBN', 'ISBN'),
               ('Title', 'Title'),
               ('Author', 'Author'),
               ('Year', 'Year')]
    select = SelectField('Search for:', choices=choices)
    search = StringField('')

@app.route("/index")
def index():
    if not session.get('logged_in'):
        return render_template('login.html')
    else:
        form = SearchForm(request.form)
        return render_template('index.html', form=form)

class RegistrationForm(Form):
    username = StringField('Username', [validators.Length(min=4, max=25)])
    email = StringField('Email Address', [validators.Length(min=6, max=35)])
    password = PasswordField('New Password', [
        validators.DataRequired(),
        validators.EqualTo('confirm', message='Passwords must match')
    ])
    confirm = PasswordField('Repeat Password')
    accept_tos = BooleanField('I accept the TOS', [validators.DataRequired()])

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm(request.form)
    if request.method == 'POST' and form.validate():
        username = form.username.data
        email = form.email.data
        password = sha256_crypt.hash(str(form.password.data))
        db.execute('INSERT INTO "Users" (name, email, password) VALUES (:name, :email, :password)',
                   {"name": username, "email": email, "password": password})
        db.commit()
        flash('Thanks for registering')
        return redirect(url_for('index'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['POST'])
def login():
    username = str(request.form['username'])
    password = str(request.form['password'])

    user = db.execute('SELECT password, id from "Users" where name = :name ',{"name": username}).fetchall()
    if len(user) == 1 and sha256_crypt.verify(str(password), user[0][0].strip()):
        session['logged_in'] = True
        session['id'] = user[0][1]
    else:
        flash('Wrong password!')
    return index()

@app.route("/logout")
def logout():
    session['logged_in'] = False
    session['id'] = None
    return index()

@app.route('/search', methods=['POST'])
def search():
    if session.get('logged_in'):
        #wyszukiwanie
        post_select = request.form['select']
        post_search = request.form['search']
        print(post_select, post_search)
        results = db.execute('SELECT * from "Books" WHERE title ILIKE :search', {"select": post_select, "search": post_search + '%'}).fetchall()
        print(results)
        if not results:
            flash('No results found!')
            return redirect('/index')
        else:
            # display results
            return render_template('results.html', results=results)

class CommentForm(Form):
    ratings = [('1', '1'),
               ('2', '2'),
               ('3', '3'),
               ('4', '4'),
               ('5', '5')]
    rating = SelectField('Rating on a scale of 1 to 5', choices=ratings)
    content = StringField('Comment', [validators.Length(min=6, max=1000)])

@app.route('/book/<int:book_id>')
def book(book_id):
    # Make sure book exists.
    book = db.execute('SELECT * FROM "Books" WHERE id = :id', {"id": book_id}).fetchone()
    if book is None:
        return render_template("error.html", message="No such book.")

    # Get all comments.
    comments = db.execute('SELECT * FROM "Comments" WHERE book_id = :book_id',
                            {"book_id": book_id}).fetchall()
    form = CommentForm(request.form)
    #Get the average rating and number of ratings the work has received from Goodreads
    res = requests.get("https://www.goodreads.com/book/review_counts.json",
                       params={"key": "C22dE1a7dzX4e32oKWeqA", "isbns": book.isbn.strip()}).json()
    return render_template("book.html", book=book, comments=comments, form=form, book_id=book_id,
                           goodreads_average_rating=res['books'][0]['average_rating'], goodreads_rating_counts=res['books'][0]['ratings_count'])

@app.route('/comment/<int:book_id>', methods=['POST'])
def comment(book_id):
    if session.get('logged_in'):
        rating = str(request.form['rating'])
        content = str(request.form['content'])
        author = session.get('id')
        #Check if user already commented on this book
        commented = db.execute('SELECT id FROM "Comments" WHERE author = :user_id AND book_id = :book_id',
                               {"user_id": author, "book_id": book_id}).fetchone()
        if not commented:
            db.execute('INSERT INTO "Comments" (book_id, author, content, rating) VALUES (:book_id, :author, :content, :rating)',
                       {"book_id": book_id, "author": author, "content": content, "rating": rating})
            db.commit()
            flash('Thanks for adding a comment')
        else:
            flash('Already commented!')
        return redirect(url_for('book' ,book_id=book_id))

@app.route('/api/<int:isbn>', methods=['GET'])
def api(isbn):
    book = db.execute('SELECT * FROM "Books" WHERE isbn = :isbn', {"isbn": str(isbn)}).fetchone()
    comments_rating = db.execute('SELECT COUNT(*), to_char(AVG (rating), \'99999999999999999D99\') FROM "Comments" '
                                 'WHERE book_id = :book_id', {"book_id": book.id}).fetchone()
    if book is None:
        abort(404)
    return jsonify({'title': book.title.strip(), 'author': book.author.strip(), 'year': book.year, 'isbn': book.isbn.strip(),
                    'review_count': comments_rating[0], 'average_score': comments_rating[1].strip()})

