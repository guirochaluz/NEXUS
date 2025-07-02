def reconciliar_vendas(ml_user_id: str,
                       desde: datetime | None = None,
                       ate: datetime | None = None,
                       max_workers: int = MAX_WORKERS
                      ) -> Dict[str, int]:
    """
    Verifica divergências entre DB e API e faz UPDATE em lote.
    Retorna {"atualizadas": X, "erros": Y}.
    """

    if desde is None:
        desde = datetime.utcnow() - relativedelta(months=6)

    db = SessionLocal()
    atualizadas = erros = 0

    try:
        # ----- token -----
        token_row: UserToken | None = db.query(UserToken).filter_by(ml_user_id=int(ml_user_id)).first()
        if not token_row:
            raise RuntimeError(f"Usuário {ml_user_id} não possui token válido.")
        access_token = token_row.access_token or ""
        novo_token = renovar_access_token(int(ml_user_id))
        if novo_token:
            access_token = novo_token

        # ----- vendas a revisar -----
        filtro_sql = """
            SELECT order_id
            FROM sales
            WHERE ml_user_id = :uid
              AND date_closed >= :desde
        """
        params = {"uid": ml_user_id, "desde": desde}

        if ate:
            filtro_sql += " AND date_closed <= :ate"
            params["ate"] = ate

        order_ids: List[str] = [r[0] for r in db.execute(text(filtro_sql), params)]

        if not order_ids:
            logging.info(f"Nenhuma venda para reconciliar entre {desde.date()} e {ate.date() if ate else 'agora'}.")
            return {"atualizadas": 0, "erros": 0}

        # ----- colunas auditáveis -----
        mapper = inspect(Sale)
        cols_to_check = {
            c.key for c in mapper.attrs
            if c.key not in {"id", "order_id", "ml_user_id"}
        }

        # ----- processamento por chunks -----
        for chunk_idx in range(0, len(order_ids), CHUNK_SIZE):
            batch = order_ids[chunk_idx:chunk_idx + CHUNK_SIZE]
            updates: List[Dict[str, Any]] = []

            # -------- thread pool --------
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                fut_to_oid = {
                    pool.submit(_fetch_full_order, oid, access_token): oid
                    for oid in batch
                }

                for fut in as_completed(fut_to_oid):
                    oid = fut_to_oid[fut]
                    full_order = fut.result()
                    if full_order is None:
                        erros += 1
                        continue

                    # DB row
                    db_row: Sale | None = db.query(Sale).filter_by(order_id=oid).first()
                    if db_row is None:
                        continue

                    # API → Sale (objeto)
                    api_sale: Sale = _order_to_sale(full_order, ml_user_id, access_token, db)

                    diff_map = {}
                    for col in cols_to_check:
                        db_val  = getattr(db_row, col)
                        api_val = getattr(api_sale, col)
                        if _is_different(db_val, api_val):
                            diff_map[col] = api_val

                    if diff_map:
                        diff_map["id"] = db_row.id
                        updates.append(diff_map)
                        logging.info(f"🔄 Order {oid} divergente – será atualizada.")

            # -------- commit do chunk --------
            if updates:
                db.bulk_update_mappings(Sale, updates)
                db.commit()
                atualizadas += len(updates)

    except Exception as e:
        db.rollback()
        raise RuntimeError(f"❌ Erro na reconciliação: {e}") from e
    finally:
        db.close()

    return {"atualizadas": atualizadas, "erros": erros}
