"""Recover only the dedicated synthetic crAPI account's orders, coupons, and credit."""

from __future__ import annotations

from catalog_order_recovery import ACTOR, owner, sql

SNAPSHOT = """SELECT json_build_object('email',u.email,'user',u.id,'credit',d.available_credit,
'orders',COALESCE((SELECT json_agg(o ORDER BY id) FROM "order" o WHERE user_id=u.id),'[]'),
'coupons',COALESCE((SELECT json_agg(c ORDER BY id) FROM applied_coupon c WHERE user_id=u.id),'[]'))
FROM user_login u JOIN user_details d ON d.user_id=u.id WHERE u.email=:'email';"""


def crapi_database(
    container: str, action: str, marker: str, before: dict | None = None
) -> dict:
    """Restore exact captured actor rows; never accept caller identity or arbitrary SQL."""
    del container, marker
    owner()
    values = {"email": ACTOR}
    statement = SNAPSHOT
    if action == "restore":
        if before is None or before.get("email") != ACTOR:
            message = "crAPI dedicated actor baseline missing"
            raise ValueError(message)
        values.update(user=str(before["user"]), credit=str(before["credit"]))
        statements = [
            "BEGIN;",
            "SELECT 1/CASE WHEN EXISTS(SELECT 1 FROM user_login WHERE id=:'user'::bigint AND email=:'email') THEN 1 ELSE 0 END;",
        ]
        identifiers = [str(row["id"]) for row in before["orders"]]
        if not all(value.isdigit() for value in identifiers):
            message = "invalid captured order identifier"
            raise ValueError(message)
        statements.append(
            "DELETE FROM \"order\" WHERE user_id=:'user'::bigint"  # noqa: S608 - only validated digit identifiers enter SQL syntax
            + (" AND id NOT IN (" + ",".join(identifiers) + ")" if identifiers else "")
            + ";"
        )
        statements.append("DELETE FROM applied_coupon WHERE user_id=:'user'::bigint;")
        for index, row in enumerate(before["orders"]):
            prefix = "order" + str(index)
            for key in (
                "id",
                "product_id",
                "quantity",
                "status",
                "created_on",
                "transaction_id",
            ):
                values[prefix + key] = str(row[key])
            statements.append(
                f"UPDATE \"order\" SET quantity=:'{prefix}quantity'::integer,status=:'{prefix}status' WHERE id=:'{prefix}id'::integer AND user_id=:'user'::bigint AND product_id=:'{prefix}product_id'::integer AND transaction_id=:'{prefix}transaction_id' AND created_on=:'{prefix}created_on'::timestamptz;"  # noqa: S608 - generated variable names with quoted psql values
            )
        for index, row in enumerate(before["coupons"]):
            values["coupon" + str(index)] = str(row["coupon_code"])
            values["couponid" + str(index)] = str(row["id"])
            statements.append(
                f"INSERT INTO applied_coupon(id,coupon_code,user_id) VALUES(:'couponid{index}'::integer,:'coupon{index}',:'user'::bigint);"
            )
        statements.extend(
            [
                "UPDATE user_details SET available_credit=:'credit'::double precision WHERE user_id=:'user'::bigint;",
                "COMMIT;",
                SNAPSHOT,
            ]
        )
        statement = "\n".join(statements)
    value = sql(statement, values)
    if value.get("email") != ACTOR or (action == "restore" and value != before):
        message = "crAPI dedicated actor restoration mismatch"
        raise ValueError(message)
    return value
