function I = convert_to_logical(A)

    dim = size(A);
    
    % make sure all dimensions are the same
    B = A(:,:,1);
    if length(dim)>=3
        dim3 = dim(3);
        for i=2:dim3
            assert(isequal(B,A(:,:,i)));
        end
    end

    maxb = max(B(:));
    minb = min(B(:));
    midb = (maxb+minb)/2;
    
    I = B > midb;
    
    ntrue = sum(I(:));
    nfalse = sum(~I(:));
    
    % convert such taht the black ink is coded as "true"
    if ntrue > nfalse
       I = ~I; 
    end
    
end