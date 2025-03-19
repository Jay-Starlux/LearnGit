# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

from datetime import datetime
from .authorize_request import AuthorizeAPI

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.addons.authorize_net.models import misc


class PaymentToken(models.Model):
    _inherit = 'payment.token'
    _rec_name = 'payment_details'

    # authorize_payment_method_type = fields.Selection(
    #     string="Authorize.Net Payment Type",
    #     help="The type of payment method this token is linked to.",
    #     selection=[("credit_card", "Credit Card"), ("bank_account", "Bank Account (USA Only)")],
    # )

    @api.model
    def default_get(self, fields):
        res = super(PaymentToken, self).default_get(fields)
        context = dict(self.env.context or {})
        if context.get('authorize') and 'default_partner_id' in context:

            if 'default_partner_id' in context and not context.get('default_partner_id'):
                raise ValidationError('Please Create Partner or configure Authorize Payment Provider.')

            partner_id = self.env['res.partner'].browse(context['default_partner_id'])
            ach_payment_method = self.env.ref("payment.payment_method_ach_direct_debit", raise_if_not_found=False)
            card_payment_method = self.env.ref("payment.payment_method_card", raise_if_not_found=False)

            payment_method_id = False
            if context.get('default_authorize_payment_method_type') == 'credit_card':
                payment_method_id = card_payment_method
            elif context.get('default_authorize_payment_method_type') == 'bank_account':
                payment_method_id = ach_payment_method

            cim_ids = partner_id.authorize_partner_ids.filtered(lambda x: x.company_id and x.company_id.id == self.env.company.id and \
                    x.payment_method_ids and payment_method_id and payment_method_id.id in x.payment_method_ids.ids)
            if not cim_ids:
                provider_id = self.env['payment.provider'].sudo()._get_authorize_provider(provider_type=context.get('default_authorize_payment_method_type'))
                if provider_id:
                    cim_ids = partner_id.authorize_customer_create(provider=provider_id, shipping_address_id=None)

            if cim_ids:
                cim_id = cim_ids and cim_ids[0]
                if cim_id and cim_id.provider_id:
                    res.update({
                        'partner_id': context['default_partner_id'],
                        'provider_ref': 'dummy',
                        'provider_id': cim_id.provider_id.id,
                        'company_id': cim_id.company_id.id,
                        'customer_profile_id': cim_id.customer_profile_id,
                        'payment_method_id': payment_method_id and payment_method_id.id or False,
                    })
                else:
                    raise ValidationError('Please configure Authorize Payment Provider.')
            else:
                raise ValidationError('Please create a customer profile for this customer from the Authorize.Net tab.')
        return res

    def _get_billing_partner_domain(self):
        domain = [('type', '=', 'invoice')]
        if self._context.get('default_partner_id'):
            domain.append(('parent_id', '=', self._context['default_partner_id']))
        return domain

    authorize_card = fields.Boolean('Authorize Card', default=False, readonly=True)
    update_value = fields.Boolean('Update Value', default=True)
    # Credit / Debit Card Fields
    credit_card_no = fields.Char('Card Number', size=16)
    credit_card_code = fields.Char('CVV', size=4)
    credit_card_type = fields.Selection([
                                ('americanexpress', 'American Express'),
                                ('visa', 'Visa'),
                                ('mastercard', 'Mastercard'),
                                ('discover', 'Discover'),
                                ('dinersclub', 'Diners Club'),
                                ('jcb', 'JCB')], 'Card Type', readonly=True)
    credit_card_expiration_month = fields.Selection([('01', '01'), ('02', '02'), ('03', '03'), ('04', '04'),
                                                     ('05', '05'), ('06', '06'), ('07', '07'), ('08', '08'),
                                                     ('09', '09'), ('10', '10'), ('11', '11'), ('12', '12'),
                                                     ('xx', 'XX')], 'Expires Month')
    credit_card_expiration_year = fields.Char('Expires Year', size=64)
    billing_partner_id = fields.Many2one('res.partner', string='Billing Partner',\
                             domain=_get_billing_partner_domain)
    # Bank Fields
    acc_number = fields.Char('Account Number', required=False)
    owner_name = fields.Char('Owner Name', size=64)
    bank_name = fields.Char('Bank Name', size=64)
    routing_number = fields.Char('Routing Number', size=9)
    authorize_bank_type = fields.Selection([('checking', 'Personal Checking'), ('savings', 'Personal Savings'),('businessChecking', 'Business Checking')], 'Authorize Bank Type')

    customer_profile_id = fields.Char(string="Profile ID")
    company_id = fields.Many2one('res.company', string='Company', index=True, copy=False)
    partner_id = fields.Many2one('res.partner', string="Customer")
    provider_id = fields.Many2one('payment.provider', string='Provider', copy=False)
    partner_ref_id = fields.Many2one(related='partner_id', string="Customer Ref ID")
    provider = fields.Selection(related='provider_id.code')

    @api.onchange('provider_id')
    def onchange_provider(self):
        if self.provider_id and self.provider_id.code == 'authorize' and self.partner_id and self.payment_method_id:
            cim_id = self.partner_id.authorize_partner_ids.filtered(lambda x: x.company_id and x.company_id.id == self.env.company.id and \
                    x.payment_method_ids and self.payment_method_id and self.payment_method_id.id in x.payment_method_ids.ids and \
                    x.provider_id and x.provider_id.id == self.provider_id.id)
            if cim_id and cim_id[0]:
                self.company_id = self.provider_id.company_id.id
                self.customer_profile_id = cim_id[0].customer_profile_id
            else:
                self.customer_profile_id = ''

    @api.model
    def search_fetch(self, domain, field_names, offset=0, limit=None, order=None):
        context = dict(self.env.context)
        # Calling from Sales Order "Confirm With Auth.Net" Button.
        if context.get('authorize') and context.get('authorize_payment_type') in ['bank_account', 'credit_card'] and (context.get('credit_card') or context.get('bank_account')):
            payment_method_id = False
            if context.get('credit_card'):
                payment_method_id = self.env.ref("payment.payment_method_card", raise_if_not_found=False)
            elif context.get('bank_account'):
                payment_method_id = self.env.ref("payment.payment_method_ach_direct_debit", raise_if_not_found=False)

            if context.get('provider_id') and payment_method_id:
                domain.append(('provider_id', '=', context.get('provider_id')))
                domain.append(('payment_method_id', '=', payment_method_id.id))
            else:
                domain = [('id', 'in', [])]

        # Calling from Invoice Register Payment
        if context.get('authorize') and context.get('payment_method_code') == 'authorize' and context.get('provider_id'):
            card_payment_method = self.env.ref("payment.payment_method_card", raise_if_not_found=False)
            ach_payment_method = self.env.ref("payment.payment_method_ach_direct_debit", raise_if_not_found=False)

            invoice_partner_id, company_id = False, False
            if context.get('payment_authorize') and context.get('invoice_id') and context.get('provider_id'):
                invoice_id = self.env['account.move'].sudo().browse(context['invoice_id'])
                invoice_partner_id = invoice_id and invoice_id.partner_id
                company_id = invoice_id and invoice_id.company_id.id

            elif not context.get('payment_authorize') and context.get('default_partner_id') and context.get('active_ids') and context.get('company_id'):
                invoice_partner_id = self.env['res.partner'].browse(context['default_partner_id'])
                company_id = context.get('company_id', False)

            cim_ids = invoice_partner_id and invoice_partner_id.authorize_partner_ids.filtered(lambda x: card_payment_method and card_payment_method.id in x.provider_id.payment_method_ids.ids)
            parent_cim_ids = invoice_partner_id and invoice_partner_id.parent_id.authorize_partner_ids.filtered(lambda x: card_payment_method and card_payment_method.id in x.provider_id.payment_method_ids.ids)

            if not cim_ids and invoice_partner_id.parent_id and parent_cim_ids:
                invoice_partner_id = invoice_partner_id.parent_id

            if invoice_partner_id:
                payment_token_ids = self.env['payment.token'].with_context({}).search([
                                            ('partner_id','=', invoice_partner_id.id),
                                            ('provider_id', '=', int(context['provider_id'])),
                                            '|', ('company_id', '=', False), ('company_id', '=', company_id)])
                domain = [('id', 'in', payment_token_ids.ids)]

            # Need to Check when we make a invoice payment
            if context.get("bank_account", False) or context.get("authorize_payment_type", False) == "bank_account":
                domain.append(('payment_method_id', '=', ach_payment_method.id))

            if context.get("credit_card", False) or context.get("authorize_payment_type", False) == "credit_card":
                domain.append(('payment_method_id', '=', card_payment_method.id))
        return super().search_fetch(domain, field_names, offset, limit, order)

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=100, order=None):
        newself = self
        context = dict(self.env.context)
        # Calling from Sales Order "Confirm With Auth.Net" Button.
        if context.get('authorize') and context.get('authorize_payment_type') in ['bank_account', 'credit_card'] and (context.get('credit_card') or context.get('bank_account')):
            payment_method_id = False
            if context.get('credit_card'):
                payment_method_id = self.env.ref("payment.payment_method_card", raise_if_not_found=False)
            elif context.get('bank_account'):
                payment_method_id = self.env.ref("payment.payment_method_ach_direct_debit", raise_if_not_found=False)

            if context.get('provider_id') and payment_method_id:
                domain.append(('provider_id', '=', context.get('provider_id')))
                domain.append(('payment_method_id', '=', payment_method_id.id))
            else:
                domain = [('id', 'in', [])]

        # Calling from Invoice Register Payment
        if context.get('authorize') and context.get('payment_method_code') == 'authorize' and context.get('provider_id'):
            card_payment_method = self.env.ref("payment.payment_method_card", raise_if_not_found=False)
            ach_payment_method = self.env.ref("payment.payment_method_ach_direct_debit", raise_if_not_found=False)

            invoice_partner_id, company_id = False, False
            if context.get('payment_authorize') and context.get('invoice_id') and context.get('provider_id'):
                invoice_id = self.env['account.move'].sudo().browse(context['invoice_id'])
                invoice_partner_id = invoice_id and invoice_id.partner_id
                company_id = invoice_id and invoice_id.company_id.id

            elif not context.get('payment_authorize') and context.get('default_partner_id') and context.get('active_ids') and context.get('company_id'):
                invoice_partner_id = self.env['res.partner'].browse(context['default_partner_id'])
                company_id = context.get('company_id', False)

            cim_ids = invoice_partner_id and invoice_partner_id.authorize_partner_ids.filtered(lambda x: card_payment_method and card_payment_method.id in x.provider_id.payment_method_ids.ids)
            parent_cim_ids = invoice_partner_id and invoice_partner_id.parent_id.authorize_partner_ids.filtered(lambda x: card_payment_method and card_payment_method.id in x.provider_id.payment_method_ids.ids)

            if not cim_ids and invoice_partner_id and invoice_partner_id.parent_id and parent_cim_ids:
                invoice_partner_id = invoice_partner_id.parent_id

            if invoice_partner_id:
                payment_token_ids = self.env['payment.token'].search([
                                            ('partner_id','=', invoice_partner_id.id),
                                            ('provider_id', '=', int(context['provider_id'])),
                                            '|', ('company_id', '=', False), ('company_id', '=', company_id)])
                domain = [('id', 'in', payment_token_ids.ids)]

            # Need to Check when we make a invoice payment
            if context.get("bank_account", False) or context.get("authorize_payment_type", False) == "bank_account":
                domain.append(('payment_method_id', '=', ach_payment_method.id))

            if context.get("credit_card", False) or context.get("authorize_payment_type", False) == "credit_card":
                domain.append(('payment_method_id', '=', card_payment_method.id))

        return super(PaymentToken, newself.with_context(context))._name_search(name=name, domain=domain, operator=operator, limit=limit, order=order)

    @api.onchange('company_id')
    def onchange_company(self):
        context = dict(self.env.context)
        if self.company_id and self.partner_id:
            ach_payment_method = self.env.ref("payment.payment_method_ach_direct_debit", raise_if_not_found=False)
            card_payment_method = self.env.ref("payment.payment_method_card", raise_if_not_found=False)

            payment_method_id = False
            if context.get('default_authorize_payment_method_type') == 'credit_card':
                payment_method_id = card_payment_method
            elif context.get('default_authorize_payment_method_type') == 'bank_account':
                payment_method_id = ach_payment_method

            cim_ids = self.partner_id.authorize_partner_ids.filtered(lambda x: x.company_id and x.company_id.id == self.company_id.id and \
                    x.payment_method_ids and payment_method_id and payment_method_id.id in x.payment_method_ids.ids)

            if not cim_ids:
                raise ValidationError(_("Please configure the provider or customer profile of the customer for '%s' company." % (self.company_id.name)))

            if cim_ids:
                cim_id = cim_ids and cim_ids[0] or False
                self.provider_id = cim_id and cim_id.provider_id.id or False
                self.customer_profile_id = cim_id and cim_id.customer_profile_id or False
            else:
                self.provider_id = False
                self.customer_profile_id = False

    @api.onchange("credit_card_no")
    def onchange_card_num(self):
        self.credit_card_type = False
        context = dict(self.env.context or {})
        if self.credit_card_no:
            self.credit_card_type = misc.cc_type(self.credit_card_no) or False
            self.partner_id = context.get('default_partner_id')
            self.payment_details = str(misc.masknumber(self.credit_card_no))

    @api.onchange("acc_number")
    def onchange_account_num(self):
        context = dict(self.env.context or {})
        if self.acc_number:
            self.partner_id = context.get('default_partner_id')
            self.payment_details = str(misc.mask_account_number(self.acc_number))

    def create_credit_card(self, values):
        context = dict(self.env.context or {})
        try:
            if values.get('provider_id') and values.get('partner_id'):
                provider_id = self.env['payment.provider'].sudo().browse(values['provider_id'])
                partner_id = self.env['res.partner'].browse(values['partner_id'])
                if not values.get('customer_profile_id'):
                    raise ValidationError(_("Please configure customer profile of the customer."))
                # customer credit Detail
                if context.get('is_import'):
                    return values
                elif values.get('customer_profile_id') and values.get('credit_card_no', False) and \
                    values.get('credit_card_code', False) and values.get('credit_card_expiration_month', False) and \
                    values.get('credit_card_expiration_year', False) and not context.get('is_import'):
                    expiry_date = values['credit_card_expiration_year'] + '-' + values['credit_card_expiration_month']
                    if datetime.now().strftime('%Y%m') > datetime.strptime(expiry_date, '%Y-%m').strftime('%Y%m'):
                        raise ValidationError(_("Card expiration date is invalid."))
                    billing_partner_id = None
                    if values.get('billing_partner_id'):
                        billing_partner_id = self.env['res.partner'].browse(values['billing_partner_id'])
                    billing_detail = partner_id.get_partner_billing_address(billing_partner_id)
                    card_details = {
                        'card_number': values['credit_card_no'],
                        'expiry_date': expiry_date,
                        'card_code': values['credit_card_code']
                    }
                    authorize_api = AuthorizeAPI(provider_id)
                    resp = authorize_api.create_customer_payment_profile(partner=self,
                                    card_details=card_details, billing=billing_detail.get('billing'), customer_profile_id=values['customer_profile_id'])
                    if resp.get('customerPaymentProfileId') and resp.get('customerProfileId'):
                        payment_profile_id = resp['customerPaymentProfileId']
                        validate_payment = authorize_api.validate_customer_payment_profile(customer_profile_id=values['customer_profile_id'], payment_profile_id=payment_profile_id)
                        if validate_payment.get('result_code') == "Ok":
                            return {
                                'payment_details': str(misc.masknumber(values['credit_card_no'])),
                                'provider_ref': str(payment_profile_id),
                                'credit_card_no': str(misc.masknumber(values['credit_card_no'])),
                                'credit_card_code': str(misc.masknumber(values['credit_card_code'])),
                                'credit_card_expiration_month': 'xx',
                                'credit_card_expiration_year': str(misc.masknumber(values['credit_card_expiration_year'])),
                                'credit_card_type': values['credit_card_type'],
                                'customer_profile_id': values['customer_profile_id'],
                                'provider_id': values.get('provider_id', False),
                                'company_id': values.get('company_id', False),
                                'authorize_profile': resp['customerProfileId'],
                                'authorize_card': True,
                                # 'authorize_payment_method_type': 'credit_card'
                                'payment_method_id': self.env.ref("payment.payment_method_card").id,
                            }
                else:
                    raise UserError(_("Please enter valid credit card details."))
            else:
                if not values.get('provider_id', False):
                    raise ValidationError(_('Please configure your Authorize.Net account'))
                if not values.get('partner_id', False):
                    raise ValidationError(_('Partner is not defined'))
        except UserError as e:
            raise UserError(_(e.args[0]))
        except ValidationError as e:
            raise ValidationError(e.args[0])
        except Exception as e:
            raise UserError(_("Authorize.NET Error! : %s !" %e))
        return values

    def create_account(self, values):
        # provider_id = self.env['payment.provider']._get_authorize_provider()
        # if not provider_id:
        #     raise ValidationError(_('Please configure your Authorize.Net account'))
        try:
            if values.get('provider_id') and values.get('partner_ref_id'):
                provider_id = self.env['payment.provider'].sudo().browse(values['provider_id'])
                partner_id = self.env['res.partner'].browse(values['partner_ref_id'])
                billing_partner_id = None
                if values.get('billing_partner_id'):
                    billing_partner_id = self.env['res.partner'].browse(values['billing_partner_id'])
                # customer Bank Detail
                if values.get('owner_name') and values.get('authorize_bank_type') and partner_id:
                    billing_detail = partner_id.get_partner_billing_address(billing_partner_id)
                    bank_details = {
                        'accountType': values.get('authorize_bank_type'),
                        'routingNumber': values.get('routing_number'),
                        'accountNumber': values.get('acc_number'),
                        'nameOnAccount': values.get('owner_name'),
                        'bankName': values.get('bank_name', '')
                    }
                    if not values.get('customer_profile_id'):
                        cid = partner_id.authorize_partner_ids.filtered(lambda x: x.company_id.id == provider_id.company_id.id and x.provider_type == 'bank_account')
                        values.update({'customer_profile_id': cid.customer_profile_id})
                    # Create the payment data for a bank account
                    authorize_api = AuthorizeAPI(provider_id)
                    resp =  authorize_api.create_customer_payment_profile(partner=self.partner_id, customer_profile_id=values.get('customer_profile_id') or self.customer_profile_id, billing=billing_detail.get('billing'), bank_details=bank_details)
                    if resp.get('customerPaymentProfileId') and resp.get('customerProfileId'):
                        payment_profile_id = resp['customerPaymentProfileId']
                        validate_payment = authorize_api.validate_customer_payment_profile(customer_profile_id=resp['customerProfileId'], payment_profile_id=payment_profile_id)
                        if validate_payment.get('result_code') == "Ok":
                            values = {
                                'partner_id': partner_id.id,
                                'payment_details': values.get('payment_details'),
                                'provider_ref': str(payment_profile_id),
                                'authorize_bank_type': values.get('authorize_bank_type'),
                                'routing_number':str(misc.mask_account_number(values['routing_number'])),
                                'acc_number': values.get('acc_number'),
                                'owner_name': values.get('owner_name'),
                                'bank_name': values.get('bank_name', False),
                                'customer_profile_id': resp['customerProfileId'],
                                'provider_id': values.get('provider_id', False),
                                'company_id': values.get('company_id', False),
                                'authorize_profile': resp['customerProfileId'],
                                # 'authorize_payment_method_type': 'bank_account'
                                'payment_method_id': self.env.ref("payment.payment_method_ach_direct_debit").id,
                            }
                            return values
                else:
                    raise ValidationError(_("Please enter proper account detail."))
        except UserError as e:
            raise UserError(_(e.args[0]))
        except ValidationError as e:
            raise ValidationError(e.args[0])
        except Exception as e:
            raise UserError(_("Authorize.NET Error! : %s !" % e))
        return True

    def update_ccd_value(self):
        if self.provider_ref:
            self.update({
                'update_value': True,
                'credit_card_code': False,
                'credit_card_type': False,
                'credit_card_no': False,
                'credit_card_expiration_month': False,
                'credit_card_expiration_year': False,
            })

    def update_acc_value(self):
        if self.provider_ref:
            self.update({
                'update_value': True,
                'acc_number': False,
                'owner_name': False,
                'bank_name': False,
                'routing_number': False,
                'authorize_bank_type': False,
            })

    def update_credit_card(self, values):
        self.ensure_one()
        context = dict(self.env.context or {})
        provider_id = self.provider_id
        if not provider_id:
            raise ValidationError(_('Please configure your Authorize.Net account'))
        try:
            if provider_id and self.customer_profile_id and values.get('credit_card_code') and \
                values.get('credit_card_expiration_year') and values.get('credit_card_expiration_month') and \
                values.get('credit_card_no'):
                expiry_date = values['credit_card_expiration_year'] + '-' + values['credit_card_expiration_month']
                if datetime.now().strftime('%Y%m') > datetime.strptime(expiry_date, '%Y-%m').strftime('%Y%m'):
                    raise ValidationError(_("Card expiration date is not valid."))

                billing_partner_id = self.billing_partner_id
                if values.get('billing_partner_id'):
                    billing_partner_id = self.env['res.partner'].browse(values['billing_partner_id'])
                billing_detail = self.partner_id.get_partner_billing_address(billing_partner_id)
                card_details = {
                    'card_number': values['credit_card_no'],
                    'expiry_date': expiry_date,
                    'card_code': values['credit_card_code']
                }
                authorize_api = AuthorizeAPI(provider_id)
                resp = authorize_api.update_customer_payment_profile(partner=self, card_details=card_details, billing=billing_detail.get('billing'),
                                        customer_profile_id=self.customer_profile_id, payment_profile_id=self.provider_ref)
                if resp.get('result_code') == "Ok":
                    validate_payment = authorize_api.validate_customer_payment_profile(customer_profile_id=self.customer_profile_id, payment_profile_id=self.provider_ref)
                    if validate_payment.get('result_code') == "Ok":
                        values.update({
                            'payment_details': str(misc.masknumber(values['credit_card_no'])),
                            'credit_card_type': values['credit_card_type'],
                            'credit_card_no': misc.masknumber(values['credit_card_no']),
                            'credit_card_code': misc.masknumber(values['credit_card_code']),
                            'credit_card_expiration_month': 'xx',
                            'credit_card_expiration_year': misc.masknumber(values['credit_card_expiration_year']),
                            'authorize_card': True,
                            'update_value': False
                        })
                return values
            else:
                raise UserError(_("Please enter valid credit card detail."))
        except UserError as e:
            raise UserError(_(e.args[0]))
        except ValidationError as e:
            raise ValidationError(e.args[0])
        except Exception as e:
            raise UserError(_("Authorize.NET Error! : %s !" %e))
        return values

    def update_account(self, values):
        self.ensure_one()
        # provider_id = self.env['payment.provider']._get_authorize_provider()
        provider_id = self.provider_id
        if not provider_id:
            raise ValidationError(_('Please configure your Authorize.Net account'))
        try:
            if self.customer_profile_id and \
                values.get('authorize_bank_type') and values.get('routing_number') and \
                values.get('acc_number'):
                billing_partner_id = self.billing_partner_id
                if values.get('billing_partner_id'):
                    billing_partner_id = self.env['res.partner'].browse(values['billing_partner_id'])
                billing_detail = self.partner_id.get_partner_billing_address(billing_partner_id)
                bank_details = {
                    'accountType': values['authorize_bank_type'],
                    'routingNumber': values['routing_number'],
                    'accountNumber': values['acc_number'],
                    'nameOnAccount': values['owner_name'],
                    'bankName': values.get('bank_name', '')
                }
                authorize_api = AuthorizeAPI(provider_id)
                resp = authorize_api.update_customer_payment_profile(
                            partner=self.partner_id, bank_details=bank_details,
                            billing=billing_detail.get('billing'),
                            customer_profile_id=self.customer_profile_id,
                            payment_profile_id=self.provider_ref)
                if resp.get('result_code') == 'Ok':
                    values.update({
                        'authorize_bank_type': values['authorize_bank_type'],
                        'routing_number': str(misc.mask_account_number(values['routing_number'])),
                        'acc_number': values['acc_number'],
                        'update_value': False
                    })
            else:
                raise ValidationError(_("Please enter proper account detail."))
        except UserError as e:
            raise UserError(_(e.args[0]))
        except ValidationError as e:
            raise ValidationError(e.args[0])
        except Exception as e:
            raise UserError(_("Authorize.NET Error! : %s !" % e))
        return values

    @api.model_create_multi
    def create(self, values_list):
        context = dict(self.env.context) or {}
        count = 0
        for values in values_list:
            if context.get('authorize') and not context.get('is_import'):
                if values.get('credit_card_no'):
                    values.update({'credit_card_type': misc.cc_type(values['credit_card_no']) or False})
                    if hasattr(self, 'create_credit_card'):
                        values.update(getattr(self, 'create_credit_card')(values))
                        fields_wl = set(self._fields) & set(values)
                        values = {field: values[field] for field in fields_wl}
                        values.update({'update_value': False})
                        values_list[count] = values
                else:
                    if hasattr(self, 'create_account'):
                        values.update(getattr(self, 'create_account')(values))
                        fields_wl = set(self._fields) & set(values)
                        values = {field: values[field] for field in fields_wl}
                        values.update({'update_value': False})
                        values_list[count] = values
                        # values.update({field: values[field] for field in fields_wl})
            count += 1
        res = super(PaymentToken, self.sudo()).create(values_list)
        # res.update({'update_value': False})
        return res

    def write(self, values):
        context = dict(self.env.context or {})
        for rec in self:
            if rec.provider_id and rec.provider_id.code == 'authorize' and rec.provider_ref and not context.get('is_import'):
                if values.get('credit_card_expiration_year') and values.get('credit_card_expiration_month') and \
                    values.get('credit_card_code') and values.get('credit_card_no'):
                    values.update({
                        'update_value': False,
                        'credit_card_type': misc.cc_type(values['credit_card_no']) or False,
                    })
                    values = rec.update_credit_card(values)
                else:
                    if values.get('authorize_bank_type') and \
                        values.get('routing_number') and values.get('acc_number'):
                        values.update({'update_value': False})
                        values = rec.update_account(values)
        return super(PaymentToken, self).write(values)

    def unlink(self):
        for rec in self:
            transaction_ids = rec.env['payment.transaction'].search([('token_id','=',rec.id)])
            if not transaction_ids:
                if rec.provider_id.code == 'authorize' and rec.provider_ref != 'dummy' and rec.partner_id:
                    authorize_api = AuthorizeAPI(rec.provider_id)
                    if rec.customer_profile_id and rec.provider_ref:
                        resp = authorize_api.unlink_customer_payment_profile(customer_profile_id=rec.customer_profile_id,
                                                                              payment_profile_id=rec.provider_ref)
            else:
                raise UserError(_("Authorize.NET Error! : Payment transaction is available for this token so you can't Delete it!"))
        return super(PaymentToken, self).unlink()
