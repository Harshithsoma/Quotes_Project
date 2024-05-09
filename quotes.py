from flask import Flask, render_template, request, redirect, make_response
from mongita import MongitaClientDisk
from bson import ObjectId
from passwords import hash_password, check_password
from datetime import datetime
app = Flask(__name__)

# open a mongita client connection
client = MongitaClientDisk()

# open a quote database
quotes_db = client.quotes_db
session_db = client.session_db
user_db = client.user_db
comment_db=client.comment_db
# Define a separate collection for comments
comment_collection = quotes_db.comment_collection

import uuid


@app.route("/", methods=["GET"])
@app.route("/quotes", methods=["GET"])
def get_quotes():
    # Retrieve session ID from cookies
    session_id = request.cookies.get("session_id", None)
    
    # Redirect to login if session ID is not present
    if not session_id:
        return redirect("/login")
    
    # Retrieve session data based on session ID
    session_collection = session_db.session_collection
    session_data = session_collection.find_one({"session_id": session_id})
    
    # Redirect to logout if session data is not found (invalid session)
    if not session_data:
        return redirect("/logout")
    
    # Extract user from session data
    user = session_data.get("user", "unknown user")
    # Retrieve quotes owned by the logged-in user
    quotes_collection = quotes_db.quotes_collection
    user_quotes = list(quotes_collection.find({"owner": user}))
    
    # Retrieve public quotes
    public_quotes = list(quotes_collection.find({"public": True}))
    
    # Combine user's quotes and public quotes
    quotes_data = user_quotes + public_quotes
    quotes_data = list({obj["_id"]: obj for obj in quotes_data}.values())
    
    search_query = request.args.get("search", "").lower()
    if search_query:
        quotes_data = [quote for quote in quotes_data if search_query in quote["text"].lower() or search_query in quote["author"].lower()]
        
    privacy_filter = request.args.get("privacy", "all")
    
    if privacy_filter == "public":
        quotes_data = [quote for quote in quotes_data if quote.get("public")]
        print(quotes_data)
    elif privacy_filter == "private":
        quotes_data = [quote for quote in quotes_data if quote.get("owner") == user]
        
    # Fetch comments for each quote and add them to the corresponding quote dictionary
    for quote in quotes_data:
        comments = comment_collection.find({"quote_id": str(quote["_id"])})
        quote["comments"] = list(comments)
    
    # Render the quotes.html template with the combined quotes data and user information
    return render_template("quotes.html", data=quotes_data, user=user)





@app.route("/login", methods=["GET"])
def get_login():
    session_id = request.cookies.get("session_id", None)
    if session_id:
        return redirect("/quotes")
    return render_template("login.html")
    

@app.route("/login", methods=["POST"])
def post_login():
    user = request.form.get("user", "")
    password = request.form.get("password", "")
    user_collection = user_db.user_collection
    user_data = list(user_collection.find({"user": user}))
    if len(user_data) != 1:
        response = redirect("/login")
        response.delete_cookie("session_id")
        return response
    hashed_password = user_data[0].get("hashed_password", "")
    salt = user_data[0].get("salt", "")
    if check_password(password, hashed_password, salt) == False:
        response = redirect("/login")
        response.delete_cookie("session_id")
        return response
    session_id = str(uuid.uuid4())
    session_collection = session_db.session_collection
    session_collection.delete_one({"session_id": session_id})
    session_data = {"session_id": session_id, "user": user}
    session_collection.insert_one(session_data)
    response = redirect("/quotes")
    response.set_cookie("session_id", session_id)
    return response


@app.route("/register", methods=["GET"])
def get_register():
    session_id = request.cookies.get("session_id", None)
    print("Pre-login session id = ", session_id)
    if session_id:
        return redirect("/quotes")
    return render_template("register.html")
    

@app.route("/register", methods=["POST"])
def post_register():
    user = request.form.get("user", "")
    password = request.form.get("password", "")
    password2 = request.form.get("password2", "")
    if password != password2:
        response = redirect("/register")
        response.delete_cookie("session_id")
        return response
    user_collection = user_db.user_collection
    user_data = list(user_collection.find({"user": user}))
    if len(user_data) == 0:
        hashed_password, salt = hash_password(password)
        user_collection.insert_one({"user": user, "hashed_password": hashed_password, "salt": salt})
    response = redirect("/login")
    response.delete_cookie("session_id")
    return response


@app.route("/logout", methods=["GET"])
def get_logout():
    session_id = request.cookies.get("session_id", None)
    if session_id:
        session_collection = session_db.session_collection
        session_collection.delete_one({"session_id": session_id})
    response = redirect("/login")
    response.delete_cookie("session_id")
    return response


@app.route("/add", methods=["GET"])
def get_create():
    session_id = request.cookies.get("session_id", None)
    if not session_id:
        response = redirect("/login")
        return response
    return render_template("add_quote.html")


@app.route("/add", methods=["POST"])
def post_create():
    session_id = request.cookies.get("session_id", None)
    if not session_id:
        response = redirect("/login")
        return response
    # get data for this session
    session_collection = session_db.session_collection
    session_data = list(session_collection.find({"session_id": session_id}))
    if len(session_data) == 0:
        response = redirect("/logout")
    assert len(session_data) == 1
    session_data = session_data[0]
    user = session_data.get("user", "unknown user")
    quote = request.form.get("quote", "")
    author = request.form.get("author", "")
    public = request.form.get("public", "") == "on"
    comments_allowed = request.form.get("comments_allowed", "") == "on"
    if quote != "" and author != "":
        created_at = datetime.now()
        quotes_collection = quotes_db.quotes_collection
        quotes_collection.insert_one({"owner": user, "text": quote, "author": author, "public": public, "created_at": created_at,"comments_allowed":comments_allowed})
    return redirect("/quotes")


    
@app.route("/edit/<id>", methods=["GET"])
def get_edit(id=None):
    session_id = request.cookies.get("session_id", None)
    if not session_id:
        return redirect("/login")
    
    if id:
        quotes_collection = quotes_db.quotes_collection
        # Get the quote by its ID
        quote = quotes_collection.find_one({"_id": ObjectId(id)})
        if quote:
            # Check if the logged-in user is the owner of the quote
            if quote.get("owner") != get_logged_in_user(session_id):
                return "You are not authorized to edit this quote."
            # Pass the quote data to the template
            quote["_id"] = str(quote["_id"])
            return render_template("edit_quote.html", data=quote)
        else:
            return "Quote not found."

    return redirect("/quotes")

def get_logged_in_user(session_id):
    session_collection = session_db.session_collection
    session_data = session_collection.find_one({"session_id": session_id})
    if session_data:
        return session_data.get("user", "")
    return ""



@app.route("/edit", methods=["POST"])
def post_edit():
    session_id = request.cookies.get("session_id", None)
    if not session_id:
        return redirect("/login")

    _id = request.form.get("_id", None)
    text = request.form.get("newQuote", "")
    author = request.form.get("newAuthor", "")
    public = request.form.get("public", "") == "on"
    comments_allowed = request.form.get("comments_allowed", "") == "on"
    if _id:
        quotes_collection = quotes_db.quotes_collection
        # Get the quote by its ID
        quote = quotes_collection.find_one({"_id": ObjectId(_id)})
        if quote:
            # Check if the logged-in user is the owner of the quote
            if quote.get("owner") != get_logged_in_user(session_id):
                return "You are not authorized to edit this quote."
            # Update the quote
            values = {"$set": {"text": text, "author": author, "public":public,"comments_allowed":comments_allowed}}
            quotes_collection.update_one({"_id": ObjectId(_id)}, values)
            return redirect("/quotes")
        else:
            return "Quote not found."

    return redirect("/quotes")

@app.route("/delete/<id>", methods=["GET"])
def get_delete(id=None):
    session_id = request.cookies.get("session_id", None)
    if not session_id:
        return redirect("/login")

    if id:
        quotes_collection = quotes_db.quotes_collection
        # Get the quote by its ID
        quote = quotes_collection.find_one({"_id": ObjectId(id)})
        if quote:
            # Check if the logged-in user is the owner of the quote
            if quote.get("owner") == get_logged_in_user(session_id):
                quotes_collection.delete_one({"_id": ObjectId(id)})
            else:
                return  "You are not authorized to delete the quote"
        else:
            return "Quote not found."

    return redirect("/quotes")




@app.route("/edit_comment/<comment_id>", methods=["GET", "POST"])
def edit_comment(comment_id):
    session_id = request.cookies.get("session_id", None)
    if not session_id:
        return redirect("/login")

    user = get_logged_in_user(session_id)
    comment_collection = quotes_db.comment_collection
    comment = comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        return "Comment not found."
    
    quote_id = comment.get("quote_id")
    quotes_collection = quotes_db.quotes_collection
    quote = quotes_collection.find_one({"_id": ObjectId(quote_id)})
    if not quote:
        return "Quote not found."
    
    comments_allowed = quote.get("comments_allowed", False)
    if not comments_allowed:
        return "Comments are not allowed for this quote."

    # Check if the logged-in user is the owner of the comment
    if comment.get("user") != user:
        return "You are not authorized to edit this comment."

    if request.method == "POST":
        new_comment_text = request.form.get("new_comment_text", "")
        # Update the comment only if the logged-in user is the owner
        if comment.get("user") == user:
            print(comment.get("user"))
            print(user)
            comment_collection.update_one({"_id": ObjectId(comment_id)}, {"$set": {"comment_text": new_comment_text}})
            return redirect("/quotes")
        else:
            return "You are not authorized to edit this comment."
    else:
        return render_template("edit_comment.html", comment=comment)

@app.route("/delete_comment/<comment_id>", methods=["GET"])
def delete_comment(comment_id):
    session_id = request.cookies.get("session_id", None)
    if not session_id:
        return redirect("/login")

    user = get_logged_in_user(session_id)
    comment_collection = quotes_db.comment_collection
    comment = comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        return "Comment not found."

    # Get the quote associated with the comment
    quotes_collection = quotes_db.quotes_collection
    quote = quotes_collection.find_one({"_id": ObjectId(comment['quote_id'])})
    print (quote.get("owner"))
    print(user)
    # Check if the logged-in user is the owner of the quote
    # if quote.get("owner") != user:
    #     return "You are not authorized to delete this comment."

    # Check if the logged-in user is the owner of the comment
    if comment.get("user") == user or quote.get("owner") == user:
        comment_collection.delete_one({"_id": ObjectId(comment_id)})
    else :
        return "You are not authorized to delete this comment."

    return redirect("/quotes")




@app.route("/add_comment/<quote_id>", methods=["GET", "POST"])
def add_comment(quote_id):
    session_id = request.cookies.get("session_id", None)
    if not session_id:
        return redirect("/login")

    user = get_logged_in_user(session_id)
    quotes_collection = quotes_db.quotes_collection
    quote = quotes_collection.find_one({"_id": ObjectId(quote_id)})
    if not quote:
        return "Quote not found."
    comments_allowed = quote.get("comments_allowed", False)
    if not comments_allowed:
        return "Comments are not allowed for this quote."
    if request.method == "POST":
        comment_text = request.form.get("comment_text", "")
        if comment_text:
            # Insert the comment into the comment collection
            comment_collection.insert_one({"quote_id": quote_id, "user": user, "comment_text": comment_text})
        
        return redirect("/quotes")
    else:
        # Render the template to allow the user to add a comment
        return render_template("add_comment.html", quote_id=quote_id)
