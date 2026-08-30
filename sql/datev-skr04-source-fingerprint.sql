WITH defaults_state AS (
  SELECT
    count(*)::bigint AS defaults_rows,
    COALESCE(min(version::text), '') AS schema_version,
    COALESCE(min(coa::text), '') AS coa,
    COALESCE(min(closedto::text), '') AS closed_to,
    COALESCE(min(accounting_method::text), '') AS accounting_method,
    COALESCE(min(profit_determination::text), '') AS profit_determination,
    COALESCE(
      md5(
        string_agg(
          md5(row_to_json(x)::text),
          ''
          ORDER BY row_to_json(x)::text
        )
      ),
      md5('')
    ) AS defaults_digest
  FROM public.defaults x
)
SELECT
  current_database() AS database_name,
  d.defaults_rows,
  d.schema_version,
  d.coa,
  d.closed_to,
  d.accounting_method,
  d.profit_determination,
  (SELECT count(*)::bigint FROM public.chart) AS chart_rows,
  (SELECT count(*)::bigint FROM public.chart WHERE charttype = 'A') AS account_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.chart x) AS chart_digest,
  (SELECT count(*)::bigint FROM public.acc_trans) AS acc_trans_rows,
  (SELECT COALESCE(min(transdate)::text, '') FROM public.acc_trans) AS first_transdate,
  (SELECT COALESCE(max(transdate)::text, '') FROM public.acc_trans) AS last_transdate,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.acc_trans_id)), md5('')) FROM public.acc_trans x) AS acc_trans_digest,
  (SELECT count(*)::bigint FROM public.ar) AS ar_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.ar x) AS ar_digest,
  (SELECT count(*)::bigint FROM public.ap) AS ap_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.ap x) AS ap_digest,
  (SELECT count(*)::bigint FROM public.gl) AS gl_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.gl x) AS gl_digest,
  (SELECT count(*)::bigint FROM public.customer) AS customer_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.customer x) AS customer_digest,
  (SELECT count(*)::bigint FROM public.vendor) AS vendor_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.vendor x) AS vendor_digest,
  (SELECT count(*)::bigint FROM public.contacts) AS contacts_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY row_to_json(x)::text)), md5('')) FROM public.contacts x) AS contacts_digest,
  (SELECT count(*)::bigint FROM public.shipto) AS shipto_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY row_to_json(x)::text)), md5('')) FROM public.shipto x) AS shipto_digest,
  (SELECT count(*)::bigint FROM public.parts) AS parts_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.parts x) AS parts_digest,
  (SELECT count(*)::bigint FROM public.oe) AS oe_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.oe x) AS oe_digest,
  (SELECT count(*)::bigint FROM public.orderitems) AS orderitems_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.orderitems x) AS orderitems_digest,
  (SELECT count(*)::bigint FROM public.delivery_orders) AS delivery_orders_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.delivery_orders x) AS delivery_orders_digest,
  (SELECT count(*)::bigint FROM public.delivery_order_items) AS delivery_order_items_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.delivery_order_items x) AS delivery_order_items_digest,
  (SELECT count(*)::bigint FROM public.invoice) AS invoice_item_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.invoice x) AS invoice_item_digest,
  (SELECT count(*)::bigint FROM public.bank_transactions) AS bank_transactions_rows,
  (SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), md5('')) FROM public.bank_transactions x) AS bank_transactions_digest,
  d.defaults_digest
FROM defaults_state d;
