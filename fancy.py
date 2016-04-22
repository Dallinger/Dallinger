

@db.scoped_session_decorator
def worker_function(vector):
    """Return the given vector."""
    img = vector
    return img


@extra_routes.route("/image", methods=["POST"])
def image_post():
    """Create an image."""
    q = Queue(connection=conn)

    job = q.enqueue(
        worker_function,
        request.values['vector'])

    return Response(
        json.dumps({"job_id": job.id}),
        status=200,
        mimetype='application/json')


@extra_routes.route("/image", methods=["GET"])
def image_get():
    """Get an image."""
    q = Queue(connection=conn)

    job = q.fetch_job(request.values['job_id'])

    return Response(
        json.dumps({"image": job.result}),
        status=200,
        mimetype='application/json')
