# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import time
import random
import logging

from .authorize_request import AuthorizeAPI

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

def _partner_split_name(partner_name):
    if partner_name: return " ".join(partner_name.split()[:-1]), partner_name.split()[-1]
    return ('', '')


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _get_card_token_domain(self):
        return [("payment_method_id","=",self.env.ref("payment.payment_method_card").id)]

    def _get_bank_token_domain(self):
        return [("payment_method_id","=",self.env.ref("payment.payment_method_ach_direct_debit").id)]

    authorize_partner_ids = fields.One2many('res.partner.authorize', 'partner_id', string='Authorize Customer', copy=False)
    email = fields.Char('Email', size=240, copy=False)

    # ============ NEW ADDED ++++++++++++
    # payment_token_ids = fields.One2many('payment.token', 'partner_id', 'Payment Tokens', domain=[('authorize_payment_method_type','=','credit_card')])
    # bank_payment_token_ids = fields.One2many('payment.token', 'partner_ref_id', 'Payment Tokens', domain=[('authorize_payment_method_type','=','bank_account')])
    payment_token_ids = fields.One2many('payment.token', 'partner_id', string='Card Payment Tokens', domain=_get_card_token_domain)
    bank_payment_token_ids = fields.One2many('payment.token', 'partner_ref_id', string='ACH Payment Tokens', domain=_get_bank_token_domain)
    # ============ NEW ADDED ++++++++++++

    def _get_customer_id(self, country):
        return "".join([country, time.strftime('%y%m%d'), str(random.randint(0, 10000)).zfill(5)]).strip()

    @api.model_create_multi
    def create(self, vals_list):
        context = dict(self.env.context or {})
        context.update({'authorize': True})
        self.env.context = context
        return super(ResPartner, self).create(vals_list)

    def write(self, values):
        context = dict(self.env.context or {})
        context.update({'authorize': True})
        self.env.context = context
        return super(ResPartner,self).write(values)

    def get_authorize_number_format(self):
        self.ensure_one()
        res = {'phone_number': '', 'fax_number': ''}
        if self.phone:
            phone_no = self.phone.replace('+', '')
            res.update({'phone_number': phone_no.replace(' ', '-')})
        return res

    def get_partner_shipping_address(self, shipping_address_id=None):
        self.ensure_one()
        context = dict(self.env.context or {})
        shipping = {}
        partner_shipping_id = self
        if shipping_address_id:
            partner_shipping_id = shipping_address_id
        if not context.get('from', False):
            shipping = partner_shipping_id.get_authorize_number_format()
        if partner_shipping_id and not partner_shipping_id.name:
            raise ValidationError(_("Please configure shipping address contact name"))
        split_name = _partner_split_name(partner_shipping_id.name)
        shipping.update({
            'first_name': '' if partner_shipping_id.is_company else split_name[0][:50],
            'last_name': split_name[1][:50] or '',
            'company': partner_shipping_id.parent_id and partner_shipping_id.parent_id.name[:50] or partner_shipping_id.name[:50] or '',
            'address': partner_shipping_id.street or '',
            'city': partner_shipping_id.city or '',
            'state': partner_shipping_id.state_id.code or '',
            'zip': partner_shipping_id.zip or '',
            'country': partner_shipping_id.country_id.code or '',
        })
        return {
            'shipping': shipping,
            'partner': partner_shipping_id,
        }

    def get_partner_billing_address(self, billing_partner_id=None):
        self.ensure_one()
        context = dict(self.env.context or {})
        billing = {}
        cus_type = 'individual'

        partner_invoice_id = self
        if billing_partner_id:
            partner_invoice_id = billing_partner_id

        if not context.get('from', False):
            billing = partner_invoice_id.get_authorize_number_format()

        if partner_invoice_id and not partner_invoice_id.name:
            raise ValidationError(_("Please configure billing address contact name"))

        split_name = _partner_split_name(partner_invoice_id.name)
        billing.update({
            'first_name': '' if partner_invoice_id.is_company else split_name[0][:50],
            'last_name': split_name[1][:50] or '',
            'company': partner_invoice_id.parent_id and partner_invoice_id.parent_id.name[:50] or partner_invoice_id.name[:50] or '',
            'address': partner_invoice_id.street or '',
            'city': partner_invoice_id.city or '',
            'state': partner_invoice_id.state_id.code or '',
            'zip': partner_invoice_id.zip or '',
            'country': partner_invoice_id.country_id.code or '',
        })
        return {
            'customer_type': cus_type,
            'billing': billing,
        }

    def authorize_customer_create(self, provider=None, shipping_address_id=None):
        self.ensure_one()
        customer_profile_ids = False
        company_id = self.env.company
        # Credit Card Provider
        # Need to check below code and remaining to update
        if not provider:
            provider = self.env['payment.provider']._get_authorize_provider(company_id=company_id)
        # Bank Provider
        # if not bank_provider and provider_type == 'bank_account':
        #     bank_provider = self.env['payment.provider']._get_authorize_provider(company_id=company_id, provider_type='bank_account')

        # if (provider_type == 'credit_card' and (not provider or provider.authorize_login == 'dummy')) or \
        #     (provider_type == 'bank_account' and (not bank_provider or bank_provider.authorize_login == 'dummy')):
        #     raise ValidationError(_('Please configure your Authorize.Net account'))

        # provider = provider if provider_type == 'credit_card' else bank_provider

        merchant_id = self._get_customer_id('CUST')
        # if self.authorize_partner_ids.filtered(lambda x: x.company_id.id == provider.company_id.id and \
        #         (provider_type == 'credit_card' and x.provider_id.authorize_login == provider.authorize_login) or \
        #         (provider_type == 'bank_account' and x.provider_id.authorize_login == bank_provider.authorize_login)):
        #     raise ValidationError("Customer profile already linked in authorize.net")
        if merchant_id:
            shipping_address = self.get_partner_shipping_address(shipping_address_id)
            try:
                partner = self
                authorize_api = AuthorizeAPI(provider)
                resp = authorize_api.create_authorize_customer_profile(partner=partner, merchant=merchant_id, shipping=shipping_address.get('shipping'))
                if resp.get('profile_id') and resp.get('shipping_address_id'):
                    customer_profile_ids = self.env['res.partner.authorize'].create({
                        'customer_profile_id': resp['profile_id'],
                        'shipping_address_id': resp['shipping_address_id'],
                        'partner_id': self.id,
                        'company_id': company_id.id,
                        'merchant_id': merchant_id,
                        'provider_id': provider.id, #if provider_type == 'credit_card' else bank_provider.id,
                    })
                    self.env.cr.commit()
            except UserError as e:
                raise UserError(_(e.args[0]))
            except ValidationError as e:
                raise ValidationError(e.args[0])
            except Exception as e:
                raise UserError(_("Authorize.NET Error! : %s !" % e))
        else:
            raise ValidationError(_("To register a customer profile we need following data of customer: "
                                    "Customer ID."))
        return customer_profile_ids
