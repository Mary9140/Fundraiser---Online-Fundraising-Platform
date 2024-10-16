from flask import Flask, render_template, request, redirect, session, flash, url_for, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO
import boto3 
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_default_secret_key')  # Use an environment variable or a default key

# AWS SES Client Configuration
ses_client = boto3.client('ses', region_name='us-east-1')  # Adjust region as needed


# Global dictionary to temporarily store invoices in memory
invoices = {}

def populate_fundraisers():
    predefined_fundraisers = [
        {'email': 'fundraiser1@example.com', 'password': 'password1'},
        {'email': 'fundraiser2@example.com', 'password': 'password2'},
        {'email': 'fundraiser3@example.com', 'password': 'password3'},
    ]

    connection = None
    cursor = None

    try:
        connection = mysql.connector.connect(
            host='database-1.cz4s62km4gyi.us-east-1.rds.amazonaws.com',
            user='admin',
            password='marychitra9100',
            database='funds'
        )
        cursor = connection.cursor()

        for fundraiser in predefined_fundraisers:
            cursor.execute("SELECT * FROM fundraisers WHERE email = %s", (fundraiser['email'],))
            if cursor.fetchone() is None:
                hashed_password = generate_password_hash(fundraiser['password'])
                cursor.execute("INSERT INTO fundraisers (email, password) VALUES (%s, %s)", 
                               (fundraiser['email'], hashed_password))
                connection.commit()

    except mysql.connector.Error as err:
        print(f'Error: {err}')
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/donate/<cause>', methods=['GET', 'POST'])
def donate(cause):
    if request.method == 'POST':
        donor_name = request.form['name']
        donor_email = request.form['email']
        donor_phone = request.form['phone_number']
        donor_address = request.form['address']
        donation_amount = request.form['amount']

        try:
            connection = mysql.connector.connect(
                host='database-1.cz4s62km4gyi.us-east-1.rds.amazonaws.com',
                user='admin',
                password='marychitra9100',
                database='funds'
            )
            cursor = connection.cursor()
            cursor.execute(f"INSERT INTO {cause}_donations (name, email, phone_number, address, amount) VALUES (%s, %s, %s, %s, %s)", 
                           (donor_name, donor_email, donor_phone, donor_address, donation_amount))
            connection.commit()
        except mysql.connector.Error as err:
            flash(f'Error: {err}', 'danger')
            return redirect(url_for('index'))
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

        invoice_buffer = generate_invoice(donor_name, donor_email, donor_phone, donor_address, donation_amount, cause)
        invoices[donor_email] = invoice_buffer

        flash('Invoice generated successfully!', 'success')

        return redirect(url_for('success', name=donor_name, amount=donation_amount, cause=cause, email=donor_email))

    return render_template('donate.html', cause=cause)

def generate_invoice(donor_name, donor_email, donor_phone, donor_address, donation_amount, cause):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.drawString(100, height - 100, "Donation Invoice")
    p.drawString(100, height - 130, f"Donor Name: {donor_name}")
    p.drawString(100, height - 150, f"Donor Email: {donor_email}")
    p.drawString(100, height - 170, f"Donor Phone: {donor_phone}")
    p.drawString(100, height - 190, f"Donor Address: {donor_address}")
    p.drawString(100, height - 210, f"Donation Amount: ${donation_amount}")
    p.drawString(100, height - 230, f"Cause: {cause.replace('-', ' ').title()}")
    p.drawString(100, height - 260, "Thank you for your generosity!")
    p.drawString(100, height - 280, f"Date: {datetime.now().strftime('%Y-%m-%d')}")

    p.save()
    buffer.seek(0)
    return buffer

@app.route('/fundraiser/login', methods=['GET', 'POST'])
def fundraiser_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        connection = None
        cursor = None

        try:
            connection = mysql.connector.connect(
                host='database-1.cz4s62km4gyi.us-east-1.rds.amazonaws.com',
                user='admin',
                password='marychitra9100',
                database='funds'
            )
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM fundraisers WHERE email = %s", (email,))
            fundraiser = cursor.fetchone()
        except mysql.connector.Error as err:
            flash(f'Error: {err}', 'danger')
            return redirect(url_for('fundraiser_login'))
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

        if fundraiser and check_password_hash(fundraiser['password'], password):
            session['fundraiser_id'] = fundraiser['id']
            flash('Login successful!', 'success')
            return redirect(url_for('fundraiser_dashboard'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('fundraiser_login.html')

@app.route('/fundraiser/dashboard')
def fundraiser_dashboard():
    if 'fundraiser_id' not in session:
        return redirect(url_for('fundraiser_login'))

    return render_template('fundraiser_dashboard.html')

@app.route('/fundraiser/dashboard/view/<cause>')
def view_donations(cause):
    if 'fundraiser_id' not in session:
        return redirect(url_for('fundraiser_login'))

    connection = None
    cursor = None

    try:
        connection = mysql.connector.connect(
            host='database-1.cz4s62km4gyi.us-east-1.rds.amazonaws.com',
            user='admin',
            password='marychitra9100',
            database='funds'
        )
        cursor = connection.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM {cause}_donations")
        donations = cursor.fetchall()
        # Calculate total donations
        cursor.execute(f"SELECT SUM(amount) AS total_donations FROM {cause}_donations")
        total_donations = cursor.fetchone()['total_donations'] or 0

    except mysql.connector.Error as err:
        flash(f'Error: {err}', 'danger')
        return redirect(url_for('fundraiser_dashboard'))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return render_template('view_donations.html', donations=donations, total_donations=total_donations)

@app.route('/download_invoice/<donor_email>')
def download_invoice(donor_email):
    if donor_email not in invoices:
        flash('Invoice not found!', 'danger')
        return redirect(url_for('index'))

    invoice_buffer = invoices[donor_email]
    return send_file(invoice_buffer, as_attachment=True, download_name=f'invoice_{donor_email}.pdf', mimetype='application/pdf')

@app.route('/logout')
def logout():
    session.pop('fundraiser_id', None)  # Remove the fundraiser_id from the session
    flash('You have been logged out.', 'success')  # Display a success message
    return redirect(url_for('index'))  # Redirect to the home page

@app.route('/success/<name>/<amount>/<cause>/<email>')
def success(name, amount, cause, email):
    return render_template('success.html', name=name, amount=amount, cause=cause.replace('-', ' ').title(), email=email)
# Function to send thank you email using AWS Lambda
def send_thank_you_email(donor_email, donation_amount, cause_name):
    lambda_client = boto3.client('lambda', region_name='us-east-1')  # Change to your region
    response = lambda_client.invoke(
        FunctionName='sendThankYouEmail',  # Replace with your actual Lambda function name
        InvocationType='Event',  # Asynchronous invocation
        Payload=json.dumps({
            'donor_email': donor_email,
            'donation_amount': donation_amount,
            'cause_name': cause_name
        })
    )


if __name__ == "__main__":
    populate_fundraisers()
    app.run(debug=True)
