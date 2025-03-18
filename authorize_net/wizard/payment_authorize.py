# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import logging

from datetime import datetime

from lxml import etree, html

from odoo.addons.authorize_net.models.authorize_request import AuthorizeAPI
from odoo.addons.authorize_net.models import misc
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SaleOrderAuthCapture(models.TransientModel):
    _name = "authorize.transaction"
    _description = "Authorize Transaction"

    @api.model
    def default_get(self, fields):
        res = super(SaleOrderAuthCapture, self).default_get(fields)
        context = dict(self.env.context or {})
        company = self.env.company

        if context.get('active_id') and context.get('active_model') == 'sale.order':
            sale_order_id = self.env['sale.order'].browse(context['active_id'])
            remaining_amount = sale_order_id.amount_total - sale_order_id.payment_amount
            company_order_id = self.env['sale.order'].search([
                                    ('user_id', '=', self.env.uid),
                                    ('id', '=', sale_order_id.id),
                                    ('company_id', 'child_of', [company.id])], limit=1)
            authorize_partner_ids = sale_order_id.partner_id.authorize_partner_ids

            if company_order_id:
                company = sale_order_id.company_id

            provider_ids = self.env['payment.provider'].with_context({'return_providers': True})._get_authorize_provider(company_id=company)
            bank_payment_method_id = self.env.ref("payment.payment_method_ach_direct_debit")
            cc_payment_method_id = self.env.ref("payment.payment_method_card")

            payment_method_id = cc_payment_method_id if context.get('authorize_payment_type') == 'credit_card' else bank_payment_method_id
            provider_ids = provider_ids.filtered(lambda x: payment_method_id and x.payment_method_ids and payment_method_id.id in x.payment_method_ids.ids)

            provider_id = provider_ids and provider_ids[0] or False
            if not provider_id:
                raise ValidationError(_("Please configure the Authorize.net provider"))

            cim_id = authorize_partner_ids.filtered(lambda x: x.provider_id and x.provider_id.id == provider_id.id)
            token = False
            if not cim_id:
                payment_token_ids = sale_order_id.partner_id.payment_token_ids

                token = payment_token_ids.filtered(lambda x: x.company_id.id == company.id and \
                                 x.provider_ref and x.provider_id.code == 'authorize' and \
                                 payment_method_id and payment_method_id.id in x.provider_id.payment_method_ids.ids)

            res.update({
                'auth_partner_id': cim_id.id if cim_id else False,
                'partner_id': sale_order_id.partner_id.id,
                'order_amount': remaining_amount,
                'merchant_id': cim_id.merchant_id if cim_id else False,
                'customer_profile_id': cim_id.customer_profile_id if cim_id else token.authorize_profile,
                'shipping_address_id': cim_id.shipping_address_id if cim_id else False,
                'company_id': cim_id.company_id.id if cim_id and cim_id.company_id else token.company_id.id,
                'provider_id': cim_id.provider_id.id if cim_id and cim_id.provider_id else token.provider_id.id,
            })
        return res

    # ===============NEW ADDED ++++++++++++++++++++
    @api.model
    def _get_authorize_payment_type(self, context=None):
        card_id = self.env.ref("payment.payment_method_card").id
        bank_id = self.env.ref("payment.payment_method_ach_direct_debit").id
        vals = []
        payment_types = self.env['payment.provider'].search([('code', '=', 'authorize'), \
                        ('company_id', '=', self.env.company.id)]).mapped('payment_method_ids').ids
        if card_id in payment_types and bank_id in payment_types:
            vals.extend([('credit_card', 'Credit Card'), ('bank_account', 'eCheck.Net')])
        elif card_id in payment_types:
            vals.extend([('credit_card', 'Credit Card')])
        elif bank_id in payment_types:
            vals.extend([('bank_account', 'eCheck.Net')])
        return vals
    # ===============NEW ADDED ++++++++++++++++++++

    def _get_billing_partner_domain(self):
        domain = [('type', '=', 'invoice')]
        context = dict(self.env.context)
        if context.get('active_id') and context.get('active_model') == 'sale.order':
            sale_order_id = self.env['sale.order'].browse(context['active_id'])
            domain.append(('parent_id', '=', sale_order_id.partner_id.id))
        return domain

    provider_id = fields.Many2one('payment.provider', string='Provider', copy=False)
    payment_method_id = fields.Many2one('payment.provider', string='Provider', copy=False)
    company_id = fields.Many2one('res.company', 'Company', index=True, copy=False)
    partner_id = fields.Many2one('res.partner', string="Partner")

    # ============== NEW ADDED +++++++++++++++++
    # authorize_payment_type = fields.Selection(selection=_get_authorize_payment_type, string='Authorize Transaction')
    authorize_payment_type = fields.Selection(selection=_get_authorize_payment_type, default="credit_card", string='Authorize Transaction')
    # ============== NEW ADDED +++++++++++++++++
    transaction_type = fields.Selection([('authorize', 'Authorize'), ('auth_capture', 'Authorize and Capture')],
                                        'Transaction Type', default='authorize')
    auth_partner_id = fields.Many2one('res.partner.authorize', string="Customer Profile", \
                        domain="[('provider_type', '=', authorize_payment_type)]")
    merchant_id = fields.Char(string='Merchant')
    customer_profile_id = fields.Char(string='Customer Profile ID', size=64, readonly=True)
    shipping_address_id = fields.Char(string='Shipping ID', size=64, readonly=True)

    # ================== NEW ADDED +++++++++++
    # payment_token_id = fields.Many2one('payment.token', string='Credit Card', domain="[('partner_id','=', partner_id), '|', ('company_id', '=', False), ('company_id', '=', company_id), ('authorize_payment_method_type', '=', 'credit_card')]")
    payment_token_id = fields.Many2one('payment.token', string='Credit Card', domain="[('partner_id','=', partner_id), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    payment_token_bank_id = fields.Many2one('payment.token', string='Bank Account', domain="[('partner_id','=', partner_id), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    # payment_token_bank_id = fields.Many2one('payment.token', string='Bank Account', domain="[('partner_id','=', partner_id), '|', ('company_id', '=', False), ('company_id', '=', company_id), ('authorize_payment_method_type', '=', 'bank_account')]")
    # ================== NEW ADDED +++++++++++
    billing_partner_id = fields.Many2one('res.partner', 'Billing Partner', domain=_get_billing_partner_domain)
    # ECHECK PAYMENT: Add BANK Fields For Direct Payment
    routing_number = fields.Char('Routing Number', size=9)
    authorize_bank_type = fields.Selection([('checking', 'Personal Checking'), ('savings', 'Personal Savings'),('businessChecking', 'Business Checking')], 'Authorize Bank Type', default='checking')
    bank_name = fields.Char('Bank Name', size=64)

    authorize_cc = fields.Boolean('Authorize Customer Credit card', default=False)
    order_amount = fields.Float('Amount')
    is_wo_save_card = fields.Boolean('Direct Payment(Without Save Card)', default=False, copy=False)
    is_wo_save_bank_acc = fields.Boolean('Direct Payment(Without Save Bank Details)', default=False, copy=False)
    cc_type = fields.Selection([('americanexpress', 'American Express'),
                                ('visa', 'Visa'),
                                ('mastercard', 'Mastercard'),
                                ('discover', 'Discover'),
                                ('dinersclub', 'Diners Club'),
                                ('jcb', 'JCB')], 'Card Type', readonly=True, copy=False)
    cc_number = fields.Char('Card Number', size=16, copy=False)
    cc_cvv = fields.Char('CVV', size=4, copy=False)
    cc_month = fields.Selection([('01', '01'), ('02', '02'), ('03', '03'), ('04', '04'),
                                                     ('05', '05'), ('06', '06'), ('07', '07'), ('08', '08'),
                                                     ('09', '09'), ('10', '10'), ('11', '11'), ('12', '12'),
                                                     ('xx', 'xx')], 'Expires Month', copy=False)
    cc_year = fields.Char('Expires Year', size=64, copy=False)
    acc_number = fields.Char('Account Number', copy=False)
    acc_name = fields.Char('Owner Name')

    @api.onchange('provider_id')
    def oncahnge_provider(self):
        if self.provider_id:
            cim_id = self.partner_id.authorize_partner_ids.filtered(lambda x: x.provider_id and self.provider_id and x.provider_id.id == self.provider_id.id)
            self.auth_partner_id = cim_id and cim_id.id or False
            self.merchant_id = cim_id and cim_id.merchant_id or False
            self.customer_profile_id = cim_id and cim_id.customer_profile_id or False
            self.shipping_address_id = cim_id and cim_id.shipping_address_id or False
            self.company_id = cim_id and cim_id.company_id.id or False
            self.payment_token_bank_id = False
            self.payment_token_id = False

    @api.onchange("cc_number", "is_wo_save_card", "authorize_payment_type", "is_wo_save_bank_acc")
    def onchange_cc_number(self):
        """ Reset fields data based on payment type
        """
        bank_payment_method_id = self.env.ref("payment.payment_method_ach_direct_debit")
        cc_payment_method_id = self.env.ref("payment.payment_method_card")
        if self.authorize_payment_type == 'bank_account':
            self.is_wo_save_card = False
            self.payment_method_id = cc_payment_method_id and cc_payment_method_id.id or False
        elif self.authorize_payment_type == 'credit_card':
            self.is_wo_save_bank_acc = False
            self.payment_method_id = bank_payment_method_id and bank_payment_method_id.id or False

        if self.is_wo_save_card:
            self.payment_token_id = False
        else:
            self.cc_number = self.cc_type = self.cc_year = self.cc_month = self.cc_cvv = self.payment_token_id = False

        if not self.is_wo_save_bank_acc:
            self.acc_number = self.acc_name = self.routing_number = False
        if self.cc_number:
            self.cc_type = misc.cc_type(self.cc_number) or False

    @api.onchange('payment_token_id', 'authorize_payment_type')
    def onchange_token_id(self):
        """ Set Authorize.net Customer Profile """
        self.ensure_one()
        context = dict(self.env.context or {})
        company = self.env.company
        sale_order_obj = self.env['sale.order']
        if self.payment_token_id and self.authorize_payment_type == 'credit_card' and not self.payment_token_id.authorize_card:
            self.update({
                'merchant_id': False,
                'customer_profile_id': self.payment_token_id.authorize_profile,
                'shipping_address_id': False,
                'provider_id': self.payment_token_id.provider_id.id
            })

        # elif context.get('active_id') and context.get('active_model') == 'sale.order':
        #     sale_order_id = sale_order_obj.browse(context['active_id'])
        #     company_order_id = sale_order_obj.search([
        #                             ('user_id', '=', self.env.uid),
        #                             ('id', '=', sale_order_id.id),
        #                             ('company_id', 'child_of', [company.id])], limit=1)
        #     authorize_partner_ids = sale_order_id.partner_id.authorize_partner_ids
        #     cid = False
        #     if self.authorize_payment_type:
        #         if company_order_id:
        #             cid = authorize_partner_ids.filtered(lambda x: x.company_id.id == sale_order_id.company_id.id and \
        #                     x.provider_type == self.authorize_payment_type)
        #         else:
        #             cid = authorize_partner_ids.filtered(lambda x: x.company_id.id == company.id and \
        #                     x.provider_type == self.authorize_payment_type)
        #     else:

        #         # ============== NEW ADDED ++++++++++++++++++
        #         card_id = self.env.ref("payment.payment_method_card").id
        #         bank_id = self.env.ref("payment.payment_method_ach_direct_debit").id
        #         # ============== NEW ADDED ++++++++++++++++++

        #         # ============== NEW ADDED ++++++++++++++++++
        #         # payment_types = self.env['payment.provider'].sudo().search([('code', '=', 'authorize'), \
        #         #         ('company_id', '=', company.id)]).mapped('authorize_payment_method_type')

        #         payment_types = self.env['payment.provider'].sudo().search([('code', '=', 'authorize'), \
        #                 ('company_id', '=', company.id)]).mapped('payment_method_ids').ids
        #         # ============== NEW ADDED ++++++++++++++++++
        #         if card_id in payment_types:
        #             if company_order_id:
        #                 cid = authorize_partner_ids.filtered(lambda x: x.company_id.id == sale_order_id.company_id.id and \
        #                         x.provider_type == 'credit_card')
        #             else:
        #                 cid = authorize_partner_ids.filtered(lambda x: x.company_id.id == company.id and \
        #                         x.provider_type == 'credit_card')
        #         elif bank_id in payment_types:
        #             if company_order_id:
        #                 cid = authorize_partner_ids.filtered(lambda x: x.company_id.id == sale_order_id.company_id.id and \
        #                         x.provider_type == 'bank_account')
        #             else:
        #                 cid = authorize_partner_ids.filtered(lambda x: x.company_id.id == company.id and \
        #                         x.provider_type == 'bank_account')
        #     if cid:
        #         self.update({
        #             'auth_partner_id': cid and cid.id or False,
        #             'merchant_id': cid.merchant_id,
        #             'customer_profile_id': cid.customer_profile_id,
        #             'shipping_address_id': cid.shipping_address_id,
        #             'company_id': cid.company_id and cid.company_id.id or False,
        #             'provider_id': cid.provider_id and cid.provider_id.id or False
        #         })

    # @api.model
    # def text_from_html(self, html_content, max_words=None, max_chars=None, ellipsis=u"…", fail=False):
    #     try:
    #         doc = html.fromstring(html_content)
    #     except (TypeError, etree.XMLSyntaxError, etree.ParserError):
    #         _logger.exception("Failure parsing this HTML:\n%s", html_content)
    #         return ""

    #     words = u"".join(doc.xpath("//text()")).split()
    #     text = u" ".join(words)

    #     return text

    def make_so_authorize_payment(self):
        """
            Make a payment of sale order using Authorize.net with selected payment mode.
        """
        self.ensure_one()
        context = dict(self.env.context or {})
        journal_obj = self.env['account.journal']
        bank_payment_method_id = self.env.ref("payment.payment_method_ach_direct_debit")
        cc_payment_method_id = self.env.ref("payment.payment_method_card")

        order_id = False
        if context.get('active_id') and context.get('active_model'):
            order_id = self.env['sale.order'].browse(context['active_id'])

        journal_id = self.provider_id and self.provider_id.journal_id or False
        if not self.provider_id or not journal_id:
            raise ValidationError(_("Please configure your Authorize.Net provider with account journal."))

        # Convert Currency Amount
        from_currency_id = order_id and order_id.currency_id
        to_currency_id = journal_id.currency_id or journal_id.company_id.currency_id
        currency_amount = self.order_amount
        if from_currency_id and to_currency_id and from_currency_id != to_currency_id:
            currency_amount = from_currency_id._convert(\
                self.order_amount, to_currency_id, journal_id.company_id, fields.Date.today())

        transaction_vals = {
            'partner_id': self.partner_id.id,
            'provider_id': self.provider_id.id,
            'amount': self.order_amount,
            'transaction_type': 'debit',
            'currency_id': order_id.currency_id.id,
            'sale_order_ids': [(6, 0, [order_id.id])],
            'company_id': self.provider_id.company_id.id,
        }
        try:
            resp = None
            if self.authorize_payment_type == 'credit_card' and order_id:
                transaction_vals["payment_method_id"] = cc_payment_method_id.id
                charge_data = {
                    'invoiceNumber': order_id.name[:19] + '/' if order_id and len(order_id.name) > 20 else (order_id.name or ''),
                    'description': order_id.note and order_id.note[:255] or '',
                    'amount': str(round(currency_amount, 2)),
                    'refId': self.merchant_id
                }
                if self.payment_token_id and not self.payment_token_id.authorize_card:
                    charge_data.update({'refId': False})
                lines = {'lineItem': []}
                count = 0
                for item in order_id.order_line:
                    count += 1
                    if not item.product_id or item.price_subtotal == 0:
                        continue
                    itemId = item.product_id.default_code or str(item.product_id.id)
                    lines['lineItem'].append({
                        'itemId': itemId[:30] + '/' if itemId and len(itemId) > 31 else (itemId or ''),
                        'name': item.product_id.name[:30] + '/' if item and item.product_id and len(item.product_id.name) > 31 else (item.product_id.name or ''),
                        'description': item.name[:254] + '/'  if len(item.name) > 255 else (item.name or ''),
                        'quantity': item.product_uom_qty and str(item.product_uom_qty).replace('-', '') or '',
                        'unitPrice': item.price_unit and str(item.price_unit).replace('-', '') or '',
                    })
                    if count == 30:
                        break
                    # if item.tax_id:
                    #     charge_data.update({'taxable': 'true'})
                charge_data.update({'line_items': lines})
                tax_id = order_id.order_line.mapped('tax_id')
                if tax_id:
                    charge_data.update({'taxable': 'true'})
                charge_data.update({'shipping_address_id': order_id.partner_shipping_id})

                if self.transaction_type == 'authorize':
                    if self.is_wo_save_card:
                        expiry_date = self.cc_year + '-' + self.cc_month
                        if datetime.now().strftime('%Y%m') > datetime.strptime(expiry_date, '%Y-%m').strftime('%Y%m'):
                            raise ValidationError(_("Expiration date not valid."))

                        billing_detail = self.partner_id.get_partner_billing_address(self.billing_partner_id)
                        # Create the payment data for a credit card
                        card_details = {
                            'cc_number': str(self.cc_number),
                            'expiry_date': expiry_date,
                            'cc_cvv': self.cc_cvv,
                            'billing': billing_detail.get('billing')
                        }
                        charge_data.update(card_details)
                        authorize_api = AuthorizeAPI(self.provider_id)
                        resp = authorize_api.authorize_charge(charge_data=charge_data)
                    else:
                        if self.payment_token_id.provider_ref:
                            authorize_api = AuthorizeAPI(self.provider_id)
                            charge_data.update({
                                'customer_profile_id': str(self.customer_profile_id),
                                'token': self.payment_token_id
                            })
                            resp = authorize_api.authorize_charge(charge_data=charge_data)
                    self.update({'cc_number': '', 'cc_cvv': '', 'cc_type': '', 'cc_year': '', 'cc_month': ''})
                    if resp is not None:
                        transaction_id = self.env['payment.transaction'].create(transaction_vals)
                        trans_id = resp.get('x_trans_id')
                        status_code = int(resp.get('x_response_code', '0'))
                        if trans_id and status_code:
                            tx_vals = {'provider_reference': str(trans_id)}
                            if not self.is_wo_save_card:
                                tx_vals.update({'token_id': self.payment_token_id.id})
                            transaction_id.write(tx_vals)
                            if status_code == 1:
                                if self.payment_token_id.provider_ref:
                                    order_id.authorize_cc = True
                                transaction_id.write({'state_message': resp.get('x_response_reason_text')})
                                transaction_id._set_authorized()
                                order_id.authorize_cc = True
                                order_id.payment_authorize = True
                                if transaction_id:
                                    order_id.write({'transaction_ids': [(4, transaction_id.id)]})
                                    # order_id.action_confirm()
                            elif status_code == 4:
                                transaction_id._set_pending()
                            else:
                                error = resp.get('x_response_reason_text', "Authorize Transaction Error")
                                _logger.info(error)
                                transaction_id._set_error(state_message=error)

                #  Applied Changes using sale order payment auth_capture
                elif self.transaction_type == 'auth_capture':
                    # Transaction amount same or less of order amount total
                    remaining_amount = order_id.amount_total - order_id.payment_amount
                    if remaining_amount < self.order_amount:
                        raise ValidationError("Transaction Failed!, Your credit amount grater than order amount.'")
                    if self.is_wo_save_card:
                        expiry_date = self.cc_year + '-' + self.cc_month
                        if datetime.now().strftime('%Y%m') > datetime.strptime(expiry_date, '%Y-%m').strftime('%Y%m'):
                            raise ValidationError(_("Expiration date not valid."))

                        billing_detail = self.partner_id.get_partner_billing_address(self.billing_partner_id)
                        # Create the payment data for a credit card
                        card_details = {
                            'card_number': str(self.cc_number),
                            'expiry_date': expiry_date,
                            'card_code': self.cc_cvv,
                        }
                        charge_data.update({'billing': billing_detail.get('billing')})
                        authorize_api = AuthorizeAPI(self.provider_id)
                        resp = authorize_api.auth_and_capture_charge(charge_data=charge_data, card_details=card_details)
                    elif self.payment_token_id.provider_ref:
                        authorize_api = AuthorizeAPI(self.provider_id)
                        charge_data.update({
                            'customer_profile_id': str(self.customer_profile_id),
                            'paymentProfileId': self.payment_token_id.provider_ref
                        })
                        resp = authorize_api.auth_and_capture_charge(charge_data=charge_data)
                    self.update({'cc_number': '', 'cc_cvv': '', 'cc_type': '', 'cc_year': '', 'cc_month': ''})
                    if resp is not None:
                        transaction_id = self.env['payment.transaction'].create(transaction_vals)
                        trans_id = resp.get('x_trans_id')
                        status_code = int(resp.get('x_response_code', '0'))
                        if trans_id and status_code:
                            tx_vals = {'provider_reference': str(trans_id)}
                            if not self.is_wo_save_card:
                                tx_vals.update({'token_id': self.payment_token_id.id})
                            transaction_id.write(tx_vals)
                            state_message = resp.get('x_response_reason_text', '')
                            if status_code == 1:
                                transaction_id._set_done(state_message=state_message)
                                order_id.payment_authorize = True
                                order_id.write({'transaction_ids': [(4, transaction_id.id)]})
                                if transaction_id:
                                    payment_id = transaction_id.create_payment_vals(\
                                                    trans_id=trans_id, authorize_partner=self, \
                                                    authorize_payment_type='credit_card')
                                    payment_id.action_post()
                                    transaction_id.write({
                                        'payment_id': payment_id.id,
                                        'is_post_processed': True
                                    })

                                amount_total_round = round(order_id.amount_total, order_id.currency_id.decimal_places)
                                payment_amount_round = round(order_id.payment_amount, order_id.currency_id.decimal_places)
                                if amount_total_round == payment_amount_round:
                                    order_id.action_confirm()
                                    _logger.info('Successfully created transaction with Transaction ID: %s', trans_id)
                            elif status_code == 4:
                                transaction_id._set_pending(state_message=state_message)
                            else:
                                error = resp.get('x_response_reason_text', "Authorize Transaction Error")
                                _logger.info(error)
                                transaction_id._set_error(state_message=error)
            elif self.authorize_payment_type == 'bank_account' and order_id:
                transaction_vals["payment_method_id"] = bank_payment_method_id.id
                charge_data = {
                    'invoiceNumber': order_id.name[:19] + '/' if order_id and len(order_id.name) > 20 else (order_id.name or ''),
                    'description': order_id.note and order_id.note[:255] or '',
                    'amount': str(round(currency_amount, 2)),
                    'refId': self.merchant_id
                }
                lines = {'lineItem': []}
                count = 0
                for item in order_id.order_line:
                    count += 1
                    if not item.product_id or item.price_subtotal == 0:
                        continue
                    itemId = item.product_id.default_code or str(item.product_id.id)
                    lines['lineItem'].append({
                        'itemId': itemId[:30] + '/' if itemId and len(itemId) > 31 else (itemId or ''),
                        'name': item.product_id.name[:30] + '/' if item and item.product_id and len(item.product_id.name) > 31 else (item.product_id.name or ''),
                        'description': item.name[:254] + '/'  if len(item.name) > 255 else (item.name or ''),
                        'quantity': item.product_uom_qty and str(item.product_uom_qty).replace('-', '') or '',
                        'unitPrice': item.price_unit and str(item.price_unit).replace('-', '') or '',
                    })
                    if count == 30:
                        break
                charge_data.update({'line_items': lines})
                # tax_id = order_id.order_line.mapped('tax_id')
                # if tax_id:
                #     charge_data.update({'taxable': 'true'})
                charge_data.update({'shipping_address_id':order_id.partner_shipping_id})

                if self.is_wo_save_bank_acc:
                    billing_detail = self.partner_id.get_partner_billing_address(self.billing_partner_id)
                    # Create the payment data for a credit card
                    bank_details = {
                        'accountType': self.authorize_bank_type,
                        'routingNumber': self.routing_number,
                        'accountNumber': self.acc_number,
                        'nameOnAccount': self.acc_name,
                    }
                    charge_data.update({'billing': billing_detail.get('billing')})
                    authorize_api = AuthorizeAPI(self.provider_id)
                    resp = authorize_api.auth_and_capture_charge(charge_data=charge_data, bank_details=bank_details)
                else:
                    if self.payment_token_bank_id.provider_ref:
                        authorize_api = AuthorizeAPI(self.provider_id)
                        charge_data.update({
                            'customer_profile_id': str(self.customer_profile_id),
                            'paymentProfileId': self.payment_token_bank_id.provider_ref
                        })
                        resp = authorize_api.auth_and_capture_charge(charge_data=charge_data)
                self.update({'acc_name': '', 'acc_number': '', 'routing_number': ''})

                payment_id = False
                if resp is not None:
                    trans_id = resp.get('x_trans_id')
                    status_code = int(resp.get('x_response_code', '0'))
                    transaction_vals.update({
                        'echeck_transaction': True,
                        'provider_reference': str(trans_id)
                    })
                    transaction_id = self.env['payment.transaction'].create(transaction_vals)
                    if trans_id and status_code and str(trans_id) != '0':
                        state_message = resp.get('x_response_reason_text', '')
                        if status_code == 1:
                            transaction_id.write({
                                'token_id': self.payment_token_bank_id.id
                            })
                            transaction_id._set_done(state_message=state_message)
                            payment_id = transaction_id.create_payment_vals(trans_id=trans_id, \
                                            authorize_partner=self, authorize_payment_type='bank_account')
                            if payment_id:
                                payment_id.action_post()
                                order_id.write({'payment_authorize': True,
                                                'authorize_bank': True})
                                order_id.action_confirm()
                            transaction_id.payment_id = payment_id.id if payment_id else False
                            transaction_id.is_post_processed = True
                        elif status_code == 4:
                            transaction_id._set_pending(state_message=state_message)
                        else:
                            error = resp.get('x_response_reason_text', "Authorize Transaction Error")
                            _logger.info(error)
                            transaction_id._set_error(state_message=error)
                    else:
                        transaction_id.update({
                            'state': 'error',
                            'state_message': 'Null Response.'
                        })
        except UserError as e:
            raise UserError(_(e.args[0]))
        except ValidationError as e:
            raise ValidationError(e.args[0])
        except Exception as e:
            raise UserError(_("Authorize.NET Error! : %s !" % e))
