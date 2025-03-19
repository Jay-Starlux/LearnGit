# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import logging
import pprint

from .authorize_request import AuthorizeAPI
from odoo import fields, models, api, _
from odoo.addons.authorize_net.models import misc
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    transaction_type = fields.Selection([
        ('debit', 'Debit'),
        ('credit', 'Credit')], 'Transaction Type', copy=False)
    refund_amount = fields.Monetary(string="Refund Amount", copy=False)
    echeck_transaction = fields.Boolean(help='Technical field for check is echeck transaction or not?', copy=False)
    company_id = fields.Many2one('res.company', related='provider_id.company_id',
            string='Company', index=True, copy=False)

    def _send_capture_request(self):
        """ Override of payment to send a capture request to Authorize.

        Note: self.ensure_one()

        :return: None
        """
        if self.provider_code != 'authorize':
            return

        # Convert Currency Amount
        from_currency_id = self.currency_id or self.company_id.currency_id
        to_currency_id = self.provider_id.journal_id.currency_id or self.provider_id.journal_id.company_id.currency_id
        currency_amount = self.amount
        if from_currency_id and to_currency_id and from_currency_id != to_currency_id:
            currency_amount = from_currency_id._convert(self.amount, to_currency_id, self.provider_id.journal_id.company_id, fields.Date.today())
            rounded_amount = round(currency_amount, self.currency_id.decimal_places)
        else:
            rounded_amount = round(self.amount, self.currency_id.decimal_places)

        authorize_API = AuthorizeAPI(self.provider_id)
        res_content = authorize_API.capture(self.provider_reference, rounded_amount)
        _logger.info(
            "capture request response for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(res_content)
        )
        feedback_data = {'reference': self.reference, 'response': res_content}
        self._handle_notification_data('authorize', feedback_data)

        # For reconcile the payment
        if not self.payment_id: self._cron_finalize_post_processing()

        if self.payment_id and self.provider_id.code == 'authorize':
            self.payment_id.authorize_payment_type = "credit_card" if self.payment_method_id.id == self.env.ref("payment.payment_method_card").id else "bank_account"
            self.payment_id.payment_method_type_id = self.payment_method_id and self.payment_method_id.id or False

        if self.payment_id and self.payment_id.state == 'draft' and self.state == 'done':
            self.payment_id.action_post()
            (self.payment_id.line_ids + self.invoice_ids.line_ids).filtered(
                lambda line: line.account_id == self.payment_id.destination_account_id
                and not line.reconciled
            ).reconcile()
            self.is_post_processed = True

    def get_payment_transaction_details(self):
        """ Send a get transaction to Authorize.

        Note: self.ensure_one()

        :return: None
        """
        self.ensure_one()
        if self.provider_code != 'authorize':
            return False

        if self.provider_reference and self.provider_id:
            authorize_api = AuthorizeAPI(self.provider_id)
            response = authorize_api.get_transaction_details(self.provider_reference)
            response.update(resultCode=response.get('messages').get('resultCode'))
            if response.get('transaction', {}).get('payment', {}).get('creditCard', False):
                response.update(x_cardNumber=response.get('transaction', {}).get('payment', {}).get('creditCard', {}).get('cardNumber', False))
            else:
                response.update(x_cardNumber=response.get('transaction', {}).get('payment', {}).get('bankAccount', {}).get('accountNumber', False))
            if response.get('resultCode') == 'Ok' and response.get('x_cardNumber'):
                return response['x_cardNumber'][4:]
            return False

    def create_payment_vals(self, trans_id=None, authorize_partner=None, authorize_payment_type='credit_card'):
        """ Create a payment of Authorize.Net payment transaction.

        Note: self.ensure_one()

        :trans_id: Authorize.Net transaction id
        :authorize_partner: Customer Profile Linked with Partner
        :authorize_payment_type: Payment Type
        :return:
        """
        self.ensure_one()
        payment_vals = {
            'amount': self.amount,
            'payment_type': 'inbound' if self.transaction_type == 'debit' else 'outbound',
            'partner_type': 'customer',
            'date': fields.Date.today(),
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'transaction_id': trans_id,
            'journal_id': self.provider_id.journal_id.id,
            'company_id': self.provider_id.company_id.id,
            'payment_token_id': self.token_id and self.token_id.id or None,
            'payment_transaction_id': self.id,
            'ref': self.reference,
            'customer_profile_id': authorize_partner.customer_profile_id,
            'merchant_id': authorize_partner.merchant_id,
            'authorize_payment_type': authorize_payment_type,
            'payment_method_type_id': self.payment_method_id and self.payment_method_id.id or False,
            'transaction_type': 'auth_capture',
        }
        payment_id = self.env['account.payment'].sudo().create(payment_vals)
        return payment_id

    def _process_feedback_data(self, data):
        super(PaymentTransaction, self)._process_feedback_data(data=data)
        self = self.sudo()

        response_content = data.get('response')
        if response_content and self.state == 'done' and not self.payment_id:
            self._cron_finalize_post_processing()
        if response_content and self.state == 'done' and self.payment_id:
            self.transaction_type = 'debit'
            if self.token_id and self.token_id.customer_profile_id:
                self.payment_id.customer_profile_id = self.token_id.customer_profile_id
            if not self.echeck_transaction and (not self.payment_id.authorize_payment_type or not self.payment_method_type_id):
                self.payment_id.authorize_payment_type = 'credit_card'
                self.payment_id.payment_method_type_id = self.env.ref("payment.payment_method_card").id
        return response_content

    def prepare_token_values(self, customer_profile_id, payment_profile_id, payment_details, authorize_API):
        """
            # Need to check this method code on Odoo.sh
        """
        card_details = payment_details.get('creditCard', False)
        bank_details = payment_details.get('bankAccount', False)
        token_vals = {
            'provider_id': self.provider_id.id,
            'partner_id': self.partner_id.id,
            'authorize_card': True,
            'provider_ref': payment_profile_id,
            'authorize_profile': customer_profile_id,
            'customer_profile_id': customer_profile_id,
        }
        if card_details:
            token_vals.update(
                payment_details=str(misc.masknumber(card_details.get('cardNumber'))) or str(misc.masknumber(card_details.get('name'))),
                credit_card_no=str(misc.masknumber(card_details.get('cardNumber'))) or str(misc.masknumber(card_details.get('name'))),
                credit_card_type=card_details.get('cardType').lower(),
                credit_card_code='XXX',
                credit_card_expiration_month='xx',
                credit_card_expiration_year='XXXX',
                payment_method_id = self.env.ref("payment.payment_method_card").id,
            )
        elif bank_details:
            bank_details = authorize_API.get_customer_payment_profile(customer_profile_id, payment_profile_id).get('paymentProfile', {}).get('payment', {}).get('bankAccount', {})
            token_vals.update(
                payment_details=str(misc.mask_account_number(bank_details.get('accountNumber'))),
                acc_number=str(misc.mask_account_number(bank_details.get('accountNumber'))),
                owner_name=bank_details.get('nameOnAccount'),
                routing_number=str(misc.mask_account_number(bank_details.get('routingNumber'))),
                authorize_bank_type=bank_details.get('accountType'),
                payment_method_id = self.env.ref("payment.payment_method_ach_direct_debit").id,
            )
        return token_vals

    def _get_partner_authorize_profile(self):
        company_id = self.env.company
        authorize_partner_id = False
        if self.provider_id and self.partner_id and self.provider_id.code == 'authorize':
            authorize_partner_id = self.partner_id.authorize_partner_ids.filtered(lambda x: \
                        x.provider_id and x.provider_id.id == self.provider_id.id and \
                        x.company_id.id == self.provider_id.company_id.id)
            authorize_API = AuthorizeAPI(self.provider_id)
        return authorize_partner_id, authorize_API, self.provider_id

    def _authorize_tokenize(self):
        """ Create a token for the current transaction.
        Note: self.ensure_one()
        :return: None
        """
        # Need to check for ACH (not getting payment profile from bank tx)
        self.ensure_one()
        token = False
        customer_profile_ids = False
        company_id = self.env.company

        authorize_API = AuthorizeAPI(self.provider_id)
        merchant_id = self.partner_id._get_customer_id('CUST')

        if not self.provider_id or self.provider_id.authorize_login == 'dummy':
            raise ValidationError(_('Please configure your Authorize.Net account'))

        cim_id = self.partner_id.authorize_partner_ids.filtered(lambda x: \
                    x.provider_id and x.provider_id.id == self.provider_id.id and \
                    x.company_id.id == self.provider_id.company_id.id)

        authorize_partner_id = False
        if self.partner_id and self.partner_id.authorize_partner_ids:
            authorize_partner_id = self.partner_id.authorize_partner_ids.filtered(lambda x: \
                        x.provider_id and x.provider_id.id == self.provider_id.id and \
                        x.company_id.id == self.provider_id.company_id.id)

        if not authorize_partner_id:
            cim_profile = authorize_API.create_customer_profile(self.partner_id, self.provider_reference, merchant_id)
            authorize_partner_id = False
            if cim_profile.get('profile_id') and cim_profile.get('shipping_address_id'):
                customer_profile_vals = {
                    'customer_profile_id': cim_profile['profile_id'],
                    'shipping_address_id': cim_profile['shipping_address_id'],
                    'partner_id': self.partner_id.id,
                    'company_id': company_id.id,
                    'merchant_id': merchant_id,
                    'provider_id': self.provider_id.id,
                }
                authorize_partner_id = self.env['res.partner.authorize'].create(customer_profile_vals)

            # Create a Token
            token_vals = self.prepare_token_values(customer_profile_id=authorize_partner_id.customer_profile_id,
                            payment_profile_id=cim_profile.get('payment_profile_id'),
                            payment_details=cim_profile.get('payment'),
                            authorize_API=authorize_API)

        else:
            transaction = authorize_API.get_transaction_details(self.provider_reference).get('transaction', {})
            transId = transaction.get('transId', '')
            customer_profile_id = authorize_partner_id[0].customer_profile_id
            payment_details = transaction.get('payment', {})
            payment_profile_id = transaction.get('profile', {}).get('customerPaymentProfileId', False)
            if not payment_profile_id:
                payment_profile = authorize_API.create_payment_profile_from_tx(transId, customer_profile_id)
                payment_profile_id = payment_profile.get('customerPaymentProfileIdList', '')[0]

            customer_profile_id = authorize_partner_id[0].customer_profile_id
            token_vals = self.prepare_token_values(customer_profile_id=customer_profile_id,
                            payment_profile_id=payment_profile_id,
                            payment_details=payment_details,
                            authorize_API=authorize_API)
        token = self.env['payment.token'].create(token_vals)
        
        self.write({
            'token_id': token.id,
            'tokenize': False,
        })
        _logger.info(
            "created token with id %s for partner with id %s", token.id, self.partner_id.id
        )
