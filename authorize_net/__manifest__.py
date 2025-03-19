# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

{
    'name': 'Backend Payment Provider: Authorize.Net',
    'version': '17.0.1.0',
    'category': 'Accounting/Payment Providers',
    'summary': 'Payment Provider: Backend Authorize.net Implementation',
    'author': 'Synconics Technologies Pvt. Ltd.',
    'website': 'http://synconics.com/',
    'description': """
    Odoo Backend Integration with Authorize.Net Payment Gateway
    Odoo Backend Integration with Authorize.Net Payment Provider
    Backend Payment Provider: Authorize.net
Authorized.net integration backend payment
United States payment gateway integration
Canada payment gateway integration
Authorize Payment Provider
Authorize.net Payment Provider
Payment Authorize
Authorized.net
accept payment
api integration
united states
UK payment gateway integration
Europe payment gateway integration
Australia payment gateway integration
visa solution
odoo authorize
    Inventory
Account
invoice
taxes
supplier
customer
journal entries
currencies
contact
integration
Import
Export
Payment followup
followup
payment reminder
reminder
payment collection
collect payment
Payment over due
overdue payment
over due
payment
customer
customer payment
customer payment overdue
overdue customer payment
customer overdue payment reminder
customer overdue payment followup
mail
payment reminder mail
due days
payment due
due payment
scheduler
analysis
followup analysis
Accounting & Auditing Terms
accounting
accounting concepts
financial management
marginal benefit
letter of credit
asset
revenue
buyer
amount due
due amount
demand
cash
cash on delivery
deferred payment
period
duration
provision
cash flow
enterpreneur
monitoring
sale
feedback
requirement
effectiveness
following
auditing
audit
management
contract management
payment
payment term
accounting
connector
product
    """,
    'depends': [
        'sale_management', 'payment_authorize'
    ],
    'data': [
        'security/authorize_security.xml',
        'security/ir.model.access.csv',
        'views/res_config_views.xml',
        'wizard/payment_authorize_view.xml',
        'wizard/account_payment_register_view.xml',
        'wizard/authorize_shipping_partner_view.xml',
        'views/void_authorize_view.xml',
        'views/refund_authorize_view.xml',
        'views/sale_view.xml',
        'views/account_invoice_view.xml',
        'views/account_payment_view.xml',
        'views/authorize_partner_view.xml',
        'views/partner_view.xml',
        'views/payment_transaction_view.xml',
        'views/payment_token_view.xml',
    ],
    'demo': [],
    'images': [
        'static/description/main_screen.png'
    ],
    'license': 'OPL-1',
    'price': 360.0,
    'currency': 'EUR',
    'installable': True,
    'application': True,
    'auto_install': False,
}
