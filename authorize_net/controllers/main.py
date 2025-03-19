# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import _, http
from odoo.http import request

from odoo.addons.payment_authorize.controllers.main import AuthorizeController

_logger = logging.getLogger(__name__)


class AuthorizeControllerExt(AuthorizeController):

    @http.route('/payment/authorize/payment', type='json', auth='public')
    def authorize_payment(self, reference, partner_id, access_token, opaque_data):
        """ Make a payment request and handle the response.

        :param str reference: The reference of the transaction
        :param int partner_id: The partner making the transaction, as a `res.partner` id
        :param str access_token: The access token used to verify the provided values
        :param dict opaque_data: The payment details obfuscated by Authorize.Net
        :return: None
        """
        # Check that the transaction details have not been altered
        tx_sudo = request.env['payment.transaction'].sudo().search([('reference', '=', reference)])
        provider_id = tx_sudo.provider_id
        company_id = provider_id and provider_id.journal_id and provider_id.journal_id.company_id
        if provider_id and partner_id and company_id:
            partner_id = request.env['res.partner'].sudo().browse(partner_id)
            customer_profile_id = False
            if partner_id.authorize_partner_ids:
                customer_profile_id = partner_id.authorize_partner_ids.filtered(lambda x: x.company_id and x.company_id.id == company_id.id)
            elif not partner_id.authorize_partner_ids:
                customer_profile_id = False
            if not customer_profile_id:
                authorize_partner = request.env['authorize.shipping.partner'].sudo()
                authorize_vals = authorize_partner.with_context({'active_model': 'res.partner', 'active_id': partner_id.id}).default_get([])
                authorize_id = authorize_partner.with_context({'active_model': 'res.partner', 'active_id': partner_id.id}).create(authorize_vals)
                authorize_id.add_shipping_authorize_cust()
        super().authorize_payment(reference=reference, partner_id=partner_id.id, access_token=access_token, opaque_data=opaque_data)


